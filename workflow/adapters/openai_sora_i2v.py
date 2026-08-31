"""OpenAI Sora 2 image-to-video adapter.

Uses the OpenAI SDK directly (not FAL) for image-to-video generation.
Accepts a start frame via `input_reference` parameter.
Pricing: ~$0.10/sec at 720p (sora-2), ~$0.30-0.50/sec (sora-2-pro).
"""

import json
import os
import sys
import time

from dotenv import load_dotenv
from openai import OpenAI

from workflow.adapters.base import Adapter, Status
from workflow.adapters.registry import register
from workflow.adapters._prompt import merge_dialogue

load_dotenv()

# Module-level client — instantiated once, not per-call
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


VALID_DURATIONS = {"4", "8", "12"}

# Map (resolution, aspect_ratio) → OpenAI size string
SIZE_MAP = {
    ("720p", "9:16"): "720x1280",
    ("720p", "16:9"): "1280x720",
    ("1080p", "9:16"): "1024x1792",
    ("1080p", "16:9"): "1792x1024",
}


@register("openai_sora_i2v")
class OpenAISoraI2VAdapter(Adapter):
    """Wraps OpenAI Sora 2 for image-to-video generation (with start frame).

    Config keys:
        prompt (str): Video generation prompt (required).
        image_path (str): Path to start frame image (required).
        output_dir (str): Directory for output video (required).
        duration (int|str): 4, 8, or 12 seconds (default 8).
        aspect_ratio (str): "9:16" or "16:9" (default "9:16").
        resolution (str): "720p" or "1080p" (default "720p").
        model (str): "sora-2" or "sora-2-pro" (default "sora-2").
        output_filename (str): Output filename (default "video_sora.mp4").
        character_ids (list[str]): Up to 2 Sora character IDs (optional).
        character_id_path (str): Path to character.json with character_id field (optional).
    """

    _jobs: dict[str, dict] = {}

    def health_check(self) -> bool:
        from workflow.adapters._health import check_openai_health
        return check_openai_health()

    @property
    def timeout_seconds(self) -> int:
        return 600

    @property
    def input_types(self) -> dict[str, str]:
        return {"image_path": "image"}

    @property
    def output_type(self) -> str:
        return "video"

    def submit(self, config: dict) -> str:
        self._preflight()
        prompt = merge_dialogue(config, style="sora")
        output_dir = config["output_dir"]

        if not prompt:
            raise ValueError("'prompt' is required")

        # Validate image_path exists
        image_path = config.get("image_path")
        if not image_path or not os.path.exists(image_path):
            raise FileNotFoundError(
                f"Start frame not found: {image_path}"
            )

        # Read image bytes for input_reference
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        os.makedirs(output_dir, exist_ok=True)

        # Normalize duration to valid string literal
        raw_duration = str(config.get("duration", 8)).rstrip("s")
        duration = raw_duration if raw_duration in VALID_DURATIONS else "8"

        # Resolve model
        model = config.get("model", "sora-2")
        if model not in ("sora-2", "sora-2-pro"):
            model = "sora-2"

        # Map resolution + aspect_ratio to size string
        resolution = config.get("resolution", "720p")
        aspect_ratio = config.get("aspect_ratio", "9:16")
        size = SIZE_MAP.get((resolution, aspect_ratio), "720x1280")

        # Resolve character IDs
        character_ids = config.get("character_ids", [])
        if isinstance(character_ids, str):
            character_ids = [character_ids]

        character_id_path = config.get("character_id_path")
        if character_id_path and os.path.exists(character_id_path):
            with open(character_id_path) as f:
                char_data = json.load(f)
            cid = char_data.get("character_id")
            if cid and cid not in character_ids:
                character_ids.append(cid)

        # Build extra_body for characters
        extra_body = None
        if character_ids:
            extra_body = {
                "characters": [{"id": cid} for cid in character_ids[:2]]
            }

        # Build payload for logging
        payload = {
            "prompt": prompt,
            "model": model,
            "seconds": duration,
            "size": size,
            "image_path": image_path,
        }
        if extra_body:
            payload["extra_body"] = extra_body

        self.log_prompt(config, payload, model=model)

        # Submit to OpenAI — use create(), NOT create_and_poll()
        client = _get_client()
        create_kwargs: dict = {
            "prompt": prompt,
            "model": model,
            "seconds": duration,
            "size": size,
            "input_reference": image_bytes,
        }
        if extra_body:
            create_kwargs["extra_body"] = extra_body

        result = client.videos.create(**create_kwargs)
        video_id = result.id

        self._jobs[video_id] = {
            "output_dir": output_dir,
            "output_filename": config.get("output_filename", "video_sora.mp4"),
            "start_time": time.time(),
        }

        print(f"  [openai_sora_i2v] Submitted video: {video_id}", file=sys.stderr)
        return video_id

    def poll(self, job_id: str) -> tuple[Status, dict]:
        job_info = self._jobs.get(job_id, {})
        elapsed = time.time() - job_info.get("start_time", time.time())
        metadata: dict = {"elapsed_seconds": round(elapsed, 1)}

        try:
            client = _get_client()
            result = client.videos.retrieve(job_id)
        except Exception as exc:
            metadata["error"] = str(exc)
            return Status.RUNNING, metadata

        status_str = result.status

        if status_str == "queued":
            metadata["progress"] = 0.0
            return Status.PENDING, metadata

        elif status_str == "in_progress":
            progress = getattr(result, "progress", 50) or 50
            metadata["progress"] = progress / 100.0
            return Status.RUNNING, metadata

        elif status_str == "completed":
            try:
                output_dir = job_info.get("output_dir", ".")
                filename = job_info.get("output_filename", "video_sora.mp4")
                output_path = os.path.join(output_dir, filename)

                # Download video via SDK — returns HttpxBinaryResponseContent
                response = client.videos.download_content(job_id)
                with open(output_path, "wb") as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)

                metadata["progress"] = 1.0
                metadata["output"] = output_path
                return Status.COMPLETED, metadata
            except Exception as exc:
                metadata["error"] = f"Failed to download result: {exc}"
                return Status.FAILED, metadata

        elif status_str == "failed":
            error_msg = str(getattr(result, "error", "Unknown error"))
            metadata["error"] = error_msg
            return Status.FAILED, metadata

        else:
            metadata["error"] = f"Unexpected status: {status_str}"
            return Status.FAILED, metadata

    def get_result(self, job_id: str) -> str:
        job_info = self._jobs.get(job_id, {})
        output_dir = job_info.get("output_dir", ".")
        filename = job_info.get("output_filename", "video_sora.mp4")
        output_path = os.path.join(output_dir, filename)
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"Result not found: {output_path}")
        return output_path
