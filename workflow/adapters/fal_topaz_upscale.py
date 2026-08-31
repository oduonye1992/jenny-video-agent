"""FAL Topaz 4x Generative Upscale adapter (Rhea-1).

Upscales AI-generated video using Topaz's Rhea-1 model, which is specifically
designed for synthetic/AI content. Always internally upscales to 4x then scales
to the target resolution.

Pricing: $0.02/sec for 720p→1080p output.
"""

import os
import sys
import time

import fal_client
import requests
from dotenv import load_dotenv

from workflow.adapters.base import Adapter, Status
from workflow.adapters.registry import register
from workflow.adapters._supabase import upload_to_supabase, VIDEO_BUCKET

load_dotenv()

TOPAZ_MODEL = "fal-ai/topaz/upscale/4x-generative-upscale"

# Target resolutions for common aspect ratios
# Topaz requires target_width >= 1280
TARGET_RESOLUTIONS = {
    "9:16": (1280, 2280),
    "16:9": (1920, 1080),
    "1:1": (1440, 1440),
}


def _download(url: str, dest: str) -> str:
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
    return dest


@register("fal_topaz_upscale")
class FalTopazUpscaleAdapter(Adapter):
    """Wraps FAL Topaz 4x Generative Upscale (Rhea-1) for AI video upscaling.

    Config keys:
        video_path (str): Local path to video to upscale (required).
        output_dir (str): Directory for output video (required).
        output_filename (str): Filename (default "upscaled.mp4").
        aspect_ratio (str): "9:16", "16:9", or "1:1" — maps to target resolution.
        target_width (int): Override target width (1280-7680).
        target_height (int): Override target height (720-4320).
        target_fps (int): Optional FPS override (16-60). Defaults to source FPS.
    """

    _jobs: dict[str, dict] = {}

    @property
    def timeout_seconds(self) -> int:
        return 600

    @property
    def input_types(self) -> dict[str, str]:
        return {"video_path": "video"}

    @property
    def output_type(self) -> str:
        return "video"

    def health_check(self) -> bool:
        from workflow.adapters._health import check_fal_health
        return check_fal_health()

    def submit(self, config: dict) -> str:
        self._preflight()
        video_path = config["video_path"]
        output_dir = config["output_dir"]

        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")

        os.makedirs(output_dir, exist_ok=True)

        # Upload video to Supabase for a public URL
        import uuid
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        uid = uuid.uuid4().hex[:8]
        video_url = upload_to_supabase(VIDEO_BUCKET, video_path, f"{ts}-{uid}-upscale-input.mp4")

        # Resolve target resolution
        aspect_ratio = config.get("aspect_ratio", "9:16")
        default_w, default_h = TARGET_RESOLUTIONS.get(aspect_ratio, (1080, 1920))
        target_width = config.get("target_width", default_w)
        target_height = config.get("target_height", default_h)

        arguments: dict = {
            "video_url": video_url,
            "target_width": target_width,
            "target_height": target_height,
        }

        target_fps = config.get("target_fps")
        if target_fps:
            arguments["target_fps"] = int(target_fps)

        # Log prompt before submitting
        self.log_prompt(config, arguments, model=TOPAZ_MODEL)

        request = fal_client.submit(TOPAZ_MODEL, arguments=arguments)
        request_id = request.request_id

        self._jobs[request_id] = {
            "output_dir": output_dir,
            "output_filename": config.get("output_filename", "upscaled.mp4"),
            "start_time": time.time(),
        }

        print(f"  [fal_topaz] Submitted upscale: {request_id} ({target_width}x{target_height})", file=sys.stderr)
        return request_id

    def poll(self, job_id: str) -> tuple[Status, dict]:
        job_info = self._jobs.get(job_id, {})
        elapsed = time.time() - job_info.get("start_time", time.time())
        metadata: dict = {"elapsed_seconds": round(elapsed, 1)}

        try:
            status = fal_client.status(TOPAZ_MODEL, job_id, with_logs=True)
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
                result = fal_client.result(TOPAZ_MODEL, job_id)
                video_url = result["video"]["url"]
                output_dir = job_info.get("output_dir", ".")
                filename = job_info.get("output_filename", "upscaled.mp4")
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
        filename = job_info.get("output_filename", "upscaled.mp4")
        output_path = os.path.join(output_dir, filename)
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"Result not found: {output_path}")
        return output_path
