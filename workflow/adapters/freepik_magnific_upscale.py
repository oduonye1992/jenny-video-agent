"""Freepik Magnific Creative Upscaler adapter.

Upscales AI-generated images using Magnific's creative upscaler via the
Freepik API. Optimized for portrait/UGC anchor frames — adds detail and
sharpness while preserving the original composition.

Used for talking head anchor frames only (one frame per video). Not used
for b-roll (multiple frames, cost adds up for marginal gain).

Pricing: ~€0.10-0.20 per image (2x upscale of a 2K portrait frame).

API docs: https://docs.freepik.com/api-reference/image-upscaler-creative/post-image-upscaler
"""

import base64
import os
import sys
import time

import requests
from dotenv import load_dotenv

from workflow.adapters.base import Adapter, Status
from workflow.adapters.registry import register

load_dotenv()

FREEPIK_API_URL = "https://api.freepik.com/v1/ai/image-upscaler"

# Optimized_for presets — map friendly names to API values
OPTIMIZE_PRESETS = {
    "standard": "standard",
    "portrait": "soft_portraits",
    "soft_portrait": "soft_portraits",
    "hard_portrait": "hard_portraits",
    "art": "art_n_illustration",
    "landscape": "nature_n_landscapes",
    "film": "films_n_photography",
    "3d": "3d_renders",
    "scifi": "science_fiction_n_horror",
}


def _image_to_base64(path: str) -> str:
    """Read a local image file and return its base64 encoding."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


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


def _api_key() -> str:
    key = os.environ.get("FREEPIK_API_KEY", "")
    if not key:
        raise RuntimeError(
            "FREEPIK_API_KEY not set. Add it to .env with your Freepik API key."
        )
    return key


@register("freepik_magnific_upscale")
class FreepikMagnificUpscaleAdapter(Adapter):
    """Wraps Freepik Magnific Creative Upscaler for AI image upscaling.

    Config keys:
        image_path (str): Local path to image to upscale (required).
        output_dir (str): Directory for output image (required).
        output_filename (str): Filename (default "upscaled.png").
        scale_factor (str): "2x", "4x", "8x", or "16x" (default "2x").
        optimized_for (str): Optimization preset (default "soft_portraits").
            Options: standard, portrait, hard_portrait, art, landscape, film, 3d, scifi.
        prompt (str): Optional guidance text for the upscale.
        creativity (int): -10 to 10, AI creativity level (default 0).
        hdr (int): -10 to 10, detail level (default 0).
        resemblance (int): -10 to 10, similarity to original (default 0).
        fractality (int): -10 to 10, prompt strength and pixel intricacy (default 0).
        engine (str): "automatic", "magnific_illusio", "magnific_sharpy",
            "magnific_sparkle" (default "automatic").
    """

    _jobs: dict[str, dict] = {}

    @property
    def timeout_seconds(self) -> int:
        return 300

    @property
    def input_types(self) -> dict[str, str]:
        return {"image_path": "image"}

    @property
    def output_type(self) -> str:
        return "image"

    def health_check(self) -> bool:
        try:
            key = os.environ.get("FREEPIK_API_KEY", "")
            return bool(key)
        except Exception:
            return False

    def submit(self, config: dict) -> str:
        self._preflight()
        image_path = config["image_path"]
        output_dir = config["output_dir"]

        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        os.makedirs(output_dir, exist_ok=True)

        # Build request payload
        image_b64 = _image_to_base64(image_path)

        scale_factor = config.get("scale_factor", "2x")
        if scale_factor not in ("2x", "4x", "8x", "16x"):
            scale_factor = "2x"

        optimized_for = config.get("optimized_for", "soft_portraits")
        optimized_for = OPTIMIZE_PRESETS.get(optimized_for, optimized_for)

        payload: dict = {
            "image": image_b64,
            "scale_factor": scale_factor,
            "optimized_for": optimized_for,
        }

        # Optional parameters
        prompt = config.get("prompt")
        if prompt:
            payload["prompt"] = prompt

        for param in ("creativity", "hdr", "resemblance", "fractality"):
            val = config.get(param)
            if val is not None:
                payload[param] = max(-10, min(10, int(val)))

        engine = config.get("engine", "automatic")
        if engine != "automatic":
            payload["engine"] = engine

        # Log prompt before submitting
        self.log_prompt(config, payload, model="magnific_creative_upscaler")

        print(f"  [magnific] Submitting upscale ({scale_factor}, {optimized_for})...", file=sys.stderr)

        headers = {
            "x-freepik-api-key": _api_key(),
            "Content-Type": "application/json",
        }

        resp = requests.post(FREEPIK_API_URL, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        task_id = data.get("data", {}).get("task_id", "")
        if not task_id:
            raise RuntimeError(f"No task_id returned from Magnific: {data}")

        self._jobs[task_id] = {
            "output_dir": output_dir,
            "output_filename": config.get("output_filename", "upscaled.png"),
            "start_time": time.time(),
        }

        print(f"  [magnific] Task submitted: {task_id}", file=sys.stderr)
        return task_id

    def poll(self, job_id: str) -> tuple[Status, dict]:
        job_info = self._jobs.get(job_id, {})
        elapsed = time.time() - job_info.get("start_time", time.time())
        metadata: dict = {"elapsed_seconds": round(elapsed, 1)}

        headers = {
            "x-freepik-api-key": _api_key(),
        }

        try:
            resp = requests.get(
                f"{FREEPIK_API_URL}/{job_id}",
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
        except Exception as exc:
            metadata["error"] = str(exc)
            return Status.RUNNING, metadata

        status = data.get("status", "").upper()

        if status in ("CREATED", "IN_PROGRESS"):
            metadata["progress"] = 0.5 if status == "IN_PROGRESS" else 0.0
            return Status.RUNNING, metadata

        elif status == "COMPLETED":
            generated = data.get("generated", [])
            if not generated:
                metadata["error"] = "Completed but no images returned"
                return Status.FAILED, metadata

            image_url = generated[0]
            output_dir = job_info.get("output_dir", ".")
            filename = job_info.get("output_filename", "upscaled.png")
            output_path = os.path.join(output_dir, filename)

            try:
                _download(image_url, output_path)
                size_kb = os.path.getsize(output_path) / 1024
                print(f"  [magnific] Saved: {output_path} ({size_kb:.0f} KB)", file=sys.stderr)
                metadata["progress"] = 1.0
                metadata["output"] = output_path
                metadata["result_url"] = image_url
                return Status.COMPLETED, metadata
            except Exception as exc:
                metadata["error"] = f"Failed to download result: {exc}"
                return Status.FAILED, metadata

        elif status == "FAILED":
            metadata["error"] = data.get("error", "Magnific upscale failed")
            return Status.FAILED, metadata

        else:
            metadata["error"] = f"Unexpected status: {status}"
            return Status.FAILED, metadata

    def get_result(self, job_id: str) -> str:
        job_info = self._jobs.get(job_id, {})
        output_dir = job_info.get("output_dir", ".")
        filename = job_info.get("output_filename", "upscaled.png")
        output_path = os.path.join(output_dir, filename)
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"Result not found: {output_path}")
        return output_path
