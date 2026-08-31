"""Nano Banana Pro scene transfer adapter.

Two-step pipeline:
  1. Gemini Flash vision → exhaustive JSON scene description (200-400 lines)
  2. Nano Banana Pro → generate image from JSON + changes

The JSON captures every surface, light bounce, shadow, fabric fold, color hex.
Nano Banana receives the raw JSON + changes instruction directly — no
intermediate merge step. The model gets the full scene data and knows exactly
what to change.

Drop-in replacement for fal_nano_banana_edit. Accepts the same reference_image
config key. Use 'changes' (or 'prompt') to describe what to modify.

Pricing: Gemini Flash (~$0.00) + Nano Banana Pro ($0.08) = ~$0.08/image.
"""

import json
import os
import sys
import time
from datetime import datetime

import fal_client
import requests
from dotenv import load_dotenv

from workflow.adapters.base import Adapter, Status
from workflow.adapters.registry import register
from workflow.adapters._supabase import upload_to_supabase, IMAGE_BUCKET

load_dotenv()

NANO_BANANA_MODEL = "fal-ai/nano-banana-pro"

VALID_ASPECT_RATIOS = {
    "9:16",
}

# ── Gemini scene description prompt ──────────────────────────────────────

DESCRIBE_SYSTEM_PROMPT = """You are a forensic image analyst for AI image generation. Your job is to reverse-engineer a photograph into an exhaustive JSON specification so detailed that an AI image model could recreate the EXACT same image from your JSON alone — every surface, every shadow, every crease.

You MUST output valid JSON and nothing else. No markdown, no code fences, no commentary before or after the JSON.

Go DEEP. Use nested objects and arrays wherever they add precision. Every distinct element gets its own object. Every accessory, every piece of furniture, every light source, every background object — broken out individually with its own properties.

For people: describe every visible body part, every finger position, every facial feature individually (eyebrows shape and arch, eye color and catchlight position, lip shape and color, nose bridge width, jawline contour). Break out each piece of clothing as its own object with type, color (exact shade name + hex if possible), material, texture, fit, condition, wrinkles, how it drapes. Each accessory (earring, ring, bracelet, watch, necklace) gets its own object with material, color, placement, size.

For environments: every visible surface gets its own entry — floor material and condition, wall material and color, ceiling if visible. Every object in the scene gets its own entry with position in frame, material, color, size, condition, wear marks. Include imperfections — scuffs, dust, stains, dog-eared pages, coffee rings.

For lighting: describe each light source individually — type, position (clock direction + elevation), color temperature in Kelvin, intensity, quality (hard/soft/diffused), what shadows it casts and where. Describe how light interacts with each surface — subsurface scattering on skin, specular highlights on metal, translucency through fabric, reflections on glass.

For color: list every dominant color with its hex code and what it belongs to. Describe the overall color grade, saturation, contrast, white balance temperature.

For camera/composition: focal length estimate, aperture estimate from DOF, sensor format feel, distance to subject, camera height and angle, composition rules, what's sharp vs blurred, bokeh quality, any lens artifacts.

Include image quality analysis: sharpness, noise/grain, compression, dynamic range, post-processing signs.

Include semantic tags and accessibility alt text.

The output should be 200-400 lines of JSON. If your output is under 200 lines, you are not being detailed enough. Go deeper. Add more nested objects. Describe more."""

REALISM_SUFFIX = """
Realism rules (apply to every generation):
- Skin: visible pores, texture variation, slight oil shine under lights, fine lines, uneven tone. Never smooth or plastic.
- Hair: frizz halo where backlight catches stray strands, varying sizes, flyaways at hairline. Never too uniform.
- Fabric: natural creases at joints from movement, wrinkles, slightly irregular patterns. Never too clean.
- Environment: real-world clutter appropriate to the setting (exit signs, cables, water bottles, lanyards, bags, scuffs). Never sterile.
- Lighting: dual color temperature — key light on subject vs different ambient on background. Never uniform across the whole image.
- Other people: must wear distinctly different outfits from the subject. Never matching.
- Gaze: match to context (panel speakers look at interviewer not camera, etc). Never default to direct-to-camera.
"""


def _build_prompt(scene_json: dict, changes: str) -> str:
    """Build the prompt: raw JSON + changes instruction for Nano Banana."""
    json_str = json.dumps(scene_json, indent=2)
    return f"{json_str}\nUse this JSON to create the image but make the changes\nChanges: {changes}\n{REALISM_SUFFIX}"


def _describe_image_with_gemini(image_path: str) -> dict:
    """Send an image to Gemini Flash and get an exhaustive JSON scene description."""
    from google import genai

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY is required for scene transfer (Gemini vision)")

    client = genai.Client(api_key=api_key)

    # Upload the image
    print(f"  [scene_transfer] Analyzing reference image with Gemini...", file=sys.stderr)

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    # Determine MIME type
    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
    mime_type = mime_map.get(ext, "image/png")

    for attempt in range(1, 4):
        response = client.models.generate_content(
            model="gemini-3-pro-image-preview",
            contents=[
                genai.types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                DESCRIBE_SYSTEM_PROMPT,
            ],
        )

        raw_text = response.text.strip()

        # Strip markdown code fences if present
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            raw_text = "\n".join(lines)

        try:
            scene_json = json.loads(raw_text)
            line_count = len(json.dumps(scene_json, indent=2).split("\n"))
            print(f"  [scene_transfer] Scene description: {line_count} lines", file=sys.stderr)
            return scene_json
        except json.JSONDecodeError as e:
            if attempt < 3:
                print(f"  [scene_transfer] Gemini returned invalid JSON (attempt {attempt}/3), retrying...", file=sys.stderr)
                continue
            raise RuntimeError(
                f"Gemini returned invalid JSON after 3 attempts: {e}\n\nRaw output (first 500 chars):\n{raw_text[:500]}"
            )


# ── Download helper ──────────────────────────────────────────────────────

def _download(url: str, dest: str) -> str:
    for attempt in range(1, 4):
        try:
            resp = requests.get(url, timeout=120)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                f.write(resp.content)
            return dest
        except Exception as e:
            if attempt == 3:
                raise RuntimeError(f"Download failed after 3 attempts: {e}")
            time.sleep(5 * attempt)
    raise RuntimeError("Download failed")


# ── Adapter ──────────────────────────────────────────────────────────────

@register("fal_nano_banana_scene_transfer")
class FalNanoBananaSceneTransferAdapter(Adapter):
    """Two-step scene transfer: Gemini describes → Nano Banana generates.

    Takes a reference image, extracts an exhaustive JSON scene description
    via Gemini Flash vision, then generates a new image from that description
    with user-specified modifications.

    Config keys:
        reference_image (str): Local path to the reference image (required).
        reference_image_url (str): Public URL of reference image (alternative).
        changes (str): What to change from the reference scene (required).
            e.g. "change the subject to a 30-year-old man with a beard"
            e.g. "same scene but at night with warm lamp light"
            e.g. "keep everything but change the wardrobe to a red dress"
        aspect_ratio (str): Output aspect ratio (default: "9:16").
        resolution (str): "0.5K", "1K", "2K", or "4K" (default: "2K").
        num_images (int): Number of variations, 1-4 (default: 1).
        output_format (str): "png", "jpeg", or "webp" (default: "png").
        output_dir (str): Directory for output image (required).
        output_filename (str): Filename (default: "scene_transfer.png").
        seed (int): Random seed (optional).
        enable_web_search (bool): Ground generation in web images. +$0.015.
        save_description (bool): Save the Gemini JSON description alongside
            the output image (default: true).
    """

    @property
    def timeout_seconds(self) -> int:
        return 300  # Gemini + Nano Banana

    @property
    def is_sync(self) -> bool:
        return True

    @property
    def input_types(self) -> dict[str, str]:
        return {"reference_image": "image"}

    @property
    def output_type(self) -> str:
        return "image"

    def health_check(self) -> bool:
        from workflow.adapters._health import check_fal_health
        return check_fal_health()

    def submit(self, config: dict) -> str:
        self._preflight()

        changes = config.get("changes") or config.get("prompt", "")
        if not changes:
            raise ValueError("'changes' (or 'prompt') is required — describe what to modify from the reference")

        # ── Step 0: Get reference image path ─────────────────────────────
        ref_path = config.get("reference_image")
        # Support reference_images list (compat with fal_nano_banana_edit)
        if not ref_path:
            ref_list = config.get("reference_images", [])
            if ref_list:
                ref_path = ref_list[0]
        ref_url = config.get("reference_image_url")
        if not ref_url:
            url_list = config.get("reference_image_urls", [])
            if url_list:
                ref_url = url_list[0]

        if ref_path and not os.path.exists(ref_path):
            raise FileNotFoundError(f"Reference image not found: {ref_path}")

        if not ref_path and ref_url:
            # Download the URL to a temp location
            output_dir = config.get("output_dir", "outputs")
            os.makedirs(output_dir, exist_ok=True)
            ref_path = os.path.join(output_dir, "_scene_transfer_ref.png")
            _download(ref_url, ref_path)

        if not ref_path:
            raise ValueError(
                "'reference_image' (local path) or 'reference_image_url' is required"
            )

        # ── Step 1: Describe the reference image with Gemini ─────────────
        scene_description = _describe_image_with_gemini(ref_path)

        # ── Step 2: Build prompt (raw JSON + changes) and generate ────────
        prompt = _build_prompt(scene_description, changes)
        output_dir = config.get("output_dir", "outputs")
        output_filename = config.get("output_filename", "scene_transfer.png")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)

        aspect_ratio = config.get("aspect_ratio", "9:16")
        if aspect_ratio not in VALID_ASPECT_RATIOS:
            aspect_ratio = "9:16"

        resolution = config.get("resolution", "2K")
        num_images = min(max(config.get("num_images", 1), 1), 4)
        output_format = config.get("output_format", "png")

        arguments: dict = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_format": output_format,
            "number_of_images": num_images,
            "enable_web_search": True
        }

        # seed = config.get("seed")
        # if seed is not None:
        #     arguments["seed"] = int(seed)

        self.log_prompt(config, arguments, model=NANO_BANANA_MODEL)

        print(
            f"  [scene_transfer] Generating image ({aspect_ratio}, {resolution})...",
            file=sys.stderr,
        )

        result = fal_client.subscribe(
            NANO_BANANA_MODEL, arguments=arguments, client_timeout=self.timeout_seconds
        )

        images = result.get("images", [])
        if not images:
            raise RuntimeError("No images returned from Nano Banana")

        # Save primary output
        _download(images[0]["url"], output_path)

        size_kb = os.path.getsize(output_path) / 1024
        print(f"  [scene_transfer] Saved: {output_path} ({size_kb:.0f} KB)", file=sys.stderr)

        # Save variations
        if num_images > 1:
            base, ext = os.path.splitext(output_filename)
            for i, img in enumerate(images[1:], start=2):
                var_path = os.path.join(output_dir, f"{base}_v{i}{ext}")
                _download(img["url"], var_path)
                print(f"  [scene_transfer] Variation {i}: {var_path}", file=sys.stderr)

        # Save the scene description JSON alongside the image
        if config.get("save_description", True):
            base_name = os.path.splitext(output_filename)[0]
            desc_path = os.path.join(output_dir, f"{base_name}_scene_description.json")
            with open(desc_path, "w") as f:
                json.dump(scene_description, f, indent=2)
            print(f"  [scene_transfer] Description saved: {desc_path}", file=sys.stderr)

            # Save the raw prompt exactly as sent to Nano Banana (plain text)
            prompt_path = os.path.join(output_dir, f"{base_name}_prompt.txt")
            with open(prompt_path, "w") as f:
                f.write(prompt)
            print(f"  [scene_transfer] Prompt saved: {prompt_path}", file=sys.stderr)

        return output_path

    def poll(self, job_id: str) -> tuple[Status, dict]:
        if os.path.exists(job_id):
            return Status.COMPLETED, {"output": job_id, "progress": 1.0}
        return Status.FAILED, {"error": f"Output not found: {job_id}"}

    def get_result(self, job_id: str) -> str:
        if not os.path.exists(job_id):
            raise FileNotFoundError(f"Result not found: {job_id}")
        return job_id
