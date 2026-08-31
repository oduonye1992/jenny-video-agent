"""FAL Nano Banana 2 image editing adapter.

Uses fal-ai/nano-banana-2/edit via the FAL API. Takes up to 14 reference
images and an edit prompt. References can be character photos, style refs,
wardrobe refs, etc. — the model combines them with the prompt to generate
a new image that preserves identity/style from the references.

Use case: Pass 1-14 character reference photos + a scene prompt to generate
an anchor image with consistent character identity.

Pricing: $0.15/image (4K = $0.30).
"""

import json
import os
import sys
import time
import uuid
from datetime import datetime

import fal_client
import requests
from dotenv import load_dotenv

from workflow.adapters.base import Adapter, Status
from workflow.adapters.registry import register
from workflow.adapters._supabase import upload_to_supabase, IMAGE_BUCKET

load_dotenv()

NANO_BANANA_EDIT_MODEL = "fal-ai/nano-banana-pro/edit"

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

VALID_ASPECT_RATIOS = {
    "9:16",
}
VALID_RESOLUTIONS = {"4K"}


def _download(url: str, dest: str) -> str:
    """Download a file from URL to local path."""
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


@register("fal_nano_banana_edit")
class FalNanoBananaEditAdapter(Adapter):
    """Wraps FAL Nano Banana 2 Edit for reference-based image generation.

    Accepts up to 14 reference images (character photos, style refs, etc.)
    combined with a prompt to generate a new image with consistent identity.

    Config keys:
        prompt (str): Scene/generation prompt (required).
        reference_images (list[str]): Local file paths to reference images (1-14).
        reference_image_urls (list[str]): Public URLs of reference images.
            Skips Supabase upload for these. Can be mixed with reference_images.
        reference_image (str): Alias for a single local path (added to reference_images).
        reference_image_url (str): Alias for a single URL (added to reference_image_urls).
        aspect_ratio (str): See VALID_ASPECT_RATIOS (default "9:16").
        resolution (str): "1K", "2K", or "4K" (default "2K").
        num_images (int): Number of variations to generate, 1-4 (default 1).
        output_format (str): "png", "jpeg", or "webp" (default "png").
        output_dir (str): Directory for output image (required).
        output_filename (str): Filename (default "edited_frame.png").
        seed (int): Random seed (optional).
        enable_web_search (bool): Ground generation in real-time web images.
            Useful for current events, real products, real places. +$0.015/image.
    """

    @property
    def timeout_seconds(self) -> int:
        return 180

    @property
    def is_sync(self) -> bool:
        return True

    @property
    def input_types(self) -> dict[str, str]:
        return {"reference_images": "image[]"}

    @property
    def output_type(self) -> str:
        return "image"

    def health_check(self) -> bool:
        from workflow.adapters._health import check_fal_health
        return check_fal_health()

    def submit(self, config: dict) -> str:
        self._preflight()

        prompt = config.get("prompt", "")
        if not prompt:
            raise ValueError("'prompt' is required")
        prompt = f"{prompt}\n{REALISM_SUFFIX}"

        # Collect all reference image URLs (up to 14)
        image_urls: list[str] = []

        # New list-based keys (preferred)
        for url in config.get("reference_image_urls", []):
            image_urls.append(url)

        # Single-key aliases
        single_url = config.get("reference_image_url")
        if single_url and single_url not in image_urls:
            image_urls.append(single_url)

        # Upload local files to Supabase
        local_paths: list[str] = list(config.get("reference_images", []))
        single_path = config.get("reference_image")
        if single_path and single_path not in local_paths:
            local_paths.append(single_path)

        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        uid = uuid.uuid4().hex[:8]
        for i, ref_path in enumerate(local_paths):
            if not os.path.exists(ref_path):
                raise FileNotFoundError(f"Reference image not found: {ref_path}")
            url = upload_to_supabase(
                IMAGE_BUCKET, ref_path, f"{ts}-{uid}-nano-edit-ref-{i}.png"
            )
            image_urls.append(url)

        if not image_urls:
            raise ValueError(
                "At least one reference image is required. "
                "Provide 'reference_images' (list of local paths) or "
                "'reference_image_urls' (list of public URLs)."
            )
        if len(image_urls) > 14:
            raise ValueError(f"Maximum 14 reference images allowed, got {len(image_urls)}")

        output_dir = config.get("output_dir", "outputs")
        output_filename = config.get("output_filename", "edited_frame.png")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)

        aspect_ratio = config.get("aspect_ratio", "9:16")
        if aspect_ratio not in VALID_ASPECT_RATIOS:
            aspect_ratio = "9:16"

        resolution = config.get("resolution", "2K")
        if resolution not in VALID_RESOLUTIONS:
            resolution = "2K"

        output_format = config.get("output_format", "png")
        num_images = min(max(config.get("num_images", 1), 1), 4)

        n_refs = len(image_urls)
        print(f"  [nano_banana_edit] Using {n_refs} reference image{'s' if n_refs != 1 else ''}",
              file=sys.stderr)

        arguments: dict = {
            "image_urls": image_urls,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_format": output_format,
            "number_of_images": num_images,
        }

        seed = config.get("seed")
        if seed is not None:
            arguments["seed"] = int(seed)

        if config.get("enable_web_search"):
            arguments["enable_web_search"] = True

        self.log_prompt(config, arguments, model=NANO_BANANA_EDIT_MODEL)

        print(
            f"  [nano_banana_edit] Editing image ({aspect_ratio}, {resolution})...",
            file=sys.stderr,
        )

        result = fal_client.subscribe(
            NANO_BANANA_EDIT_MODEL, arguments=arguments, client_timeout=self.timeout_seconds
        )

        images = result.get("images", [])
        if not images:
            raise RuntimeError("No images returned from FAL Nano Banana Edit")

        # Save first image (primary output)
        result_url = images[0]["url"]
        _download(result_url, output_path)

        size_kb = os.path.getsize(output_path) / 1024
        print(f"  [nano_banana_edit] Saved: {output_path} ({size_kb:.0f} KB)", file=sys.stderr)

        # Save the raw prompt alongside the image
        base_name = os.path.splitext(output_filename)[0]
        prompt_path = os.path.join(output_dir, f"{base_name}_prompt.txt")
        with open(prompt_path, "w") as f:
            f.write(f"Model: {NANO_BANANA_EDIT_MODEL}\n")
            f.write(f"Reference images: {len(image_urls)}\n")
            for i, url in enumerate(image_urls):
                f.write(f"  [{i}]: {url}\n")
            f.write(f"\nPrompt:\n{prompt}\n")
            f.write(f"\nFull arguments:\n{json.dumps(arguments, indent=2)}\n")
        print(f"  [nano_banana_edit] Prompt saved: {prompt_path}", file=sys.stderr)

        # Save additional variations if requested
        if num_images > 1:
            base, ext = os.path.splitext(output_filename)
            for i, img in enumerate(images[1:], start=2):
                var_path = os.path.join(output_dir, f"{base}_v{i}{ext}")
                _download(img["url"], var_path)
                print(f"  [nano_banana_edit] Variation {i}: {var_path}", file=sys.stderr)

        return output_path

    def poll(self, job_id: str) -> tuple[Status, dict]:
        if os.path.exists(job_id):
            return Status.COMPLETED, {"output": job_id, "progress": 1.0}
        return Status.FAILED, {"error": f"Output not found: {job_id}"}

    def get_result(self, job_id: str) -> str:
        if not os.path.exists(job_id):
            raise FileNotFoundError(f"Result not found: {job_id}")
        return job_id
