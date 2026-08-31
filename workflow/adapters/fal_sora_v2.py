"""FAL Sora 2 Pro image-to-video adapter.

Uses fal-ai/sora-2/image-to-video/pro via the FAL API.
Pricing: ~$0.50/sec at 1080p.
"""

import os
import sys
import time
import uuid
from datetime import datetime

import json

import fal_client
import requests
from dotenv import load_dotenv

from workflow.adapters.base import Adapter, Status
from workflow.adapters.registry import register
from workflow.adapters._supabase import upload_to_supabase, IMAGE_BUCKET
from workflow.adapters._prompt import merge_dialogue

load_dotenv()

SORA_MODEL = "fal-ai/sora-2/image-to-video/pro"

VALID_DURATIONS = {4, 8, 12}


def _download(url: str, dest: str) -> str:
    """Download a file from URL to local path."""
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return dest


@register("fal_sora_v2")
class FalSoraAdapter(Adapter):
    """Wraps FAL Sora 2 Pro for image-to-video generation.

    Config keys:
        start_frame_path (str): Local path to start frame image (required).
        prompt (str): Video generation prompt (required).
        output_dir (str): Directory for output video (required).
        duration (int): 4, 8, or 12 seconds (default 8).
        aspect_ratio (str): "16:9", "9:16", or "auto" (default "auto").
        resolution (str): "720p", "1080p", or "auto" (default "720p").
        output_filename (str): Output filename (default "video_sora.mp4").
        character_ids (list[str]): Up to 2 Sora character IDs (optional).
            Characters must be created via fal-ai/sora-2/characters endpoint.
            Reference character by name in the prompt text.
    """

    _jobs: dict[str, dict] = {}

    def health_check(self) -> bool:
        from workflow.adapters._health import check_fal_health
        return check_fal_health()

    @property
    def timeout_seconds(self) -> int:
        return 600

    @property
    def input_types(self) -> dict[str, str]:
        return {"start_frame_path": "image"}

    @property
    def output_type(self) -> str:
        return "video"

    def submit(self, config: dict) -> str:
        self._preflight()
        start_frame_path = config["start_frame_path"]
        prompt = merge_dialogue(config, style="sora")
        output_dir = config["output_dir"]

        if not prompt:
            raise ValueError("'prompt' is required")
        if not os.path.exists(start_frame_path):
            raise FileNotFoundError(f"Start frame not found: {start_frame_path}")

        os.makedirs(output_dir, exist_ok=True)

        # Normalize duration
        raw_duration = int(str(config.get("duration", 8)).rstrip("s"))
        duration = raw_duration if raw_duration in VALID_DURATIONS else 8

        resolution = config.get("resolution", "720p")
        if resolution not in ("720p", "1080p", "auto"):
            resolution = "720p"

        aspect_ratio = config.get("aspect_ratio", "auto")

        # Upload frame to Supabase for public URL
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        uid = uuid.uuid4().hex[:8]
        image_url = upload_to_supabase(IMAGE_BUCKET, start_frame_path, f"{ts}-{uid}-sora-start.png")

        arguments: dict = {
            "prompt": prompt,
            "image_url": image_url,
            "duration": duration,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
        }

        # Character IDs — up to 2 Sora character IDs for consistent identity.
        # Can come from config directly or resolved from a character.json via *_from.
        character_ids = config.get("character_ids", [])
        if isinstance(character_ids, str):
            character_ids = [character_ids]

        # Resolve character_id_path (from DAG *_from resolution) into character_ids
        character_id_path = config.get("character_id_path")
        if character_id_path and os.path.exists(character_id_path):
            with open(character_id_path) as f:
                char_data = json.load(f)
            cid = char_data.get("character_id")
            if cid and cid not in character_ids:
                character_ids.append(cid)

        if character_ids:
            arguments["character_ids"] = character_ids[:2]

        self.log_prompt(config, arguments, model=SORA_MODEL)

        request = fal_client.submit(SORA_MODEL, arguments=arguments)
        request_id = request.request_id

        self._jobs[request_id] = {
            "output_dir": output_dir,
            "output_filename": config.get("output_filename", "video_sora.mp4"),
            "start_time": time.time(),
        }

        print(f"  [fal_sora_v2] Submitted request: {request_id}", file=sys.stderr)
        return request_id

    def poll(self, job_id: str) -> tuple[Status, dict]:
        job_info = self._jobs.get(job_id, {})
        elapsed = time.time() - job_info.get("start_time", time.time())
        metadata: dict = {"elapsed_seconds": round(elapsed, 1)}

        try:
            status = fal_client.status(SORA_MODEL, job_id, with_logs=True)
        except Exception as exc:
            metadata["error"] = str(exc)
            return Status.RUNNING, metadata

        if isinstance(status, fal_client.Queued):
            metadata["progress"] = 0.0
            if hasattr(status, "position"):
                metadata["queue_position"] = status.position
            return Status.PENDING, metadata

        elif isinstance(status, fal_client.InProgress):
            metadata["progress"] = 0.5
            return Status.RUNNING, metadata

        elif isinstance(status, fal_client.Completed):
            try:
                result = fal_client.result(SORA_MODEL, job_id)
                video_url = result["video"]["url"]
                output_dir = job_info.get("output_dir", ".")
                filename = job_info.get("output_filename", "video_sora.mp4")
                output_path = os.path.join(output_dir, filename)
                _download(video_url, output_path)
                metadata["progress"] = 1.0
                metadata["output"] = output_path
                metadata["result_url"] = video_url
                return Status.COMPLETED, metadata
            except Exception as exc:
                metadata["error"] = f"Failed to download result: {exc}"
                return Status.FAILED, metadata

        else:
            metadata["error"] = f"Unexpected FAL status type: {type(status).__name__}"
            return Status.FAILED, metadata

    def get_result(self, job_id: str) -> str:
        job_info = self._jobs.get(job_id, {})
        output_dir = job_info.get("output_dir", ".")
        filename = job_info.get("output_filename", "video_sora.mp4")
        output_path = os.path.join(output_dir, filename)
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"Result not found: {output_path}")
        return output_path
