"""FAL Nano Banana 2 text-to-image adapter.

Uses fal-ai/nano-banana-2 via the FAL API. Synchronous — submits and
polls until the image is ready.

Pricing: $0.08/image.
"""

import os
import sys
import time
from datetime import datetime

import fal_client
import requests
from dotenv import load_dotenv

from workflow.adapters.base import Adapter, Status
from workflow.adapters.registry import register

load_dotenv()

NANO_BANANA_MODEL = "fal-ai/nano-banana-2"

VALID_ASPECT_RATIOS = {
    "auto", "21:9", "16:9", "3:2", "4:3", "5:4",
    "1:1", "4:5", "3:4", "2:3", "9:16",
}
VALID_RESOLUTIONS = {"0.5K", "1K", "2K", "4K"}


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


def _extract_from_spec(spec: dict) -> dict:
    """Extract prompt, negative_prompt, aspect_ratio from a Nano Banana JSON spec.

    Same logic as the Replicate adapter — the spec follows the schema in
    ``nano-banana-prompt.md``. The ``prompt`` object is stringified as JSON.
    """
    import json
    result = {}

    prompt_obj = spec.get("prompt", {})
    if prompt_obj:
        result["prompt"] = json.dumps(prompt_obj, indent=2)

    neg = spec.get("negative_prompt", [])
    if isinstance(neg, list) and neg:
        result["negative_prompt"] = ", ".join(neg)
    elif isinstance(neg, str) and neg:
        result["negative_prompt"] = neg

    meta = spec.get("meta", {})
    gen = spec.get("generation_settings", {})
    ar = meta.get("aspect_ratio") or gen.get("aspect_ratio")
    if ar:
        result["aspect_ratio"] = ar

    resolution = gen.get("resolution") or gen.get("quality")
    if resolution:
        result["resolution"] = resolution

    return result


@register("fal_nano_banana_v2")
class FalNanoBananaAdapter(Adapter):
    """Wraps FAL Nano Banana 2 for text-to-image generation.

    Config keys (plain prompt):
        prompt (str): Image generation prompt (required).
        aspect_ratio (str): See VALID_ASPECT_RATIOS (default "9:16").
        resolution (str): "0.5K", "1K", "2K", or "4K" (default "2K").
        output_format (str): "png", "jpeg", or "webp" (default "png").
        output_dir (str): Directory for output image (required).
        output_filename (str): Filename (default "frame.png").
        seed (int): Random seed (optional).

    Config keys (full spec):
        nano_banana_spec (dict): Full Nano Banana JSON spec. When provided,
            the adapter extracts prompt, aspect_ratio, etc. from the spec.

    Extra:
        num_images (int): Number of variations to generate, 1-4 (default 1).
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
        return {}

    @property
    def output_type(self) -> str:
        return "image"

    def health_check(self) -> bool:
        from workflow.adapters._health import check_fal_health
        return check_fal_health()

    def submit(self, config: dict) -> str:
        self._preflight()
        # If a full Nano Banana spec is provided, extract fields from it
        # The structured JSON prompt from the spec is preferred over the flat text prompt
        spec = config.get("nano_banana_spec")
        if spec and isinstance(spec, dict):
            extracted = _extract_from_spec(spec)
            prompt = extracted.get("prompt", "") or config.get("prompt", "")
            aspect_ratio = extracted.get("aspect_ratio") or config.get("aspect_ratio", "9:16")
            resolution = extracted.get("resolution") or config.get("resolution", "2K")
        else:
            prompt = config.get("prompt", "")
            aspect_ratio = config.get("aspect_ratio", "9:16")
            resolution = config.get("resolution", "2K")

        if not prompt:
            raise ValueError("'prompt' (or 'nano_banana_spec.prompt') is required")

        output_dir = config.get("output_dir", "outputs")
        output_filename = config.get("output_filename", "frame.png")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)

        if aspect_ratio not in VALID_ASPECT_RATIOS:
            aspect_ratio = "9:16"
        if resolution not in VALID_RESOLUTIONS:
            resolution = "1K"

        output_format = config.get("output_format", "png")
        num_images = min(max(config.get("num_images", 1), 1), 4)

        arguments: dict = {
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

        # Log prompt before generating
        self.log_prompt(config, arguments, model=NANO_BANANA_MODEL)

        print(f"  [fal_nano_banana] Generating image ({aspect_ratio}, {resolution})...", file=sys.stderr)

        # FAL Nano Banana is fast — use sync subscribe with timeout
        result = fal_client.subscribe(NANO_BANANA_MODEL, arguments=arguments, client_timeout=self.timeout_seconds)

        images = result.get("images", [])
        if not images:
            raise RuntimeError("No images returned from FAL Nano Banana")

        # Save first image (primary output)
        _download(images[0]["url"], output_path)

        size_kb = os.path.getsize(output_path) / 1024
        print(f"  [fal_nano_banana] Saved: {output_path} ({size_kb:.0f} KB)", file=sys.stderr)

        # Save additional variations if requested
        if num_images > 1:
            base, ext = os.path.splitext(output_filename)
            for i, img in enumerate(images[1:], start=2):
                var_path = os.path.join(output_dir, f"{base}_v{i}{ext}")
                _download(img["url"], var_path)
                print(f"  [fal_nano_banana] Variation {i}: {var_path}", file=sys.stderr)

        return output_path

    def poll(self, job_id: str) -> tuple[Status, dict]:
        # Sync adapter — submit() blocks until complete
        if os.path.exists(job_id):
            return Status.COMPLETED, {"output": job_id, "progress": 1.0}
        return Status.FAILED, {"error": f"Output not found: {job_id}"}

    def get_result(self, job_id: str) -> str:
        if not os.path.exists(job_id):
            raise FileNotFoundError(f"Result not found: {job_id}")
        return job_id
