"""FAL LTX Video 2.0 Pro image-to-video adapter.

Budget-friendly video generation with audio sync.
$0.06/sec at 1080p, up to 20 seconds.
"""

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
from workflow.adapters._prompt import merge_dialogue

load_dotenv()

LTX_MODEL = "fal-ai/ltxv-2/image-to-video"


def _download(url: str, dest: str) -> str:
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return dest


@register("fal_ltx_v2")
class FalLtxAdapter(Adapter):
    """Wraps FAL LTX Video 2.0 Pro image-to-video generation.

    Config keys:
        start_frame_path (str): Local path to start frame image (required).
        prompt (str): Motion/scene prompt (required).
        output_dir (str): Directory for output video (required).
        duration (int): Video duration in seconds: 6, 8, 10, 12, 14, 16, 18, 20 (default 8).
        resolution (str): "720p", "1080p", "1440p", or "2160p" (default "720p").
        fps (int): 25 or 50 (default 25).
        generate_audio (bool): Whether to generate synchronized audio (default True).
        output_filename (str): Output filename (default "video_ltx.mp4").
    """

    _jobs: dict[str, dict] = {}

    @property
    def timeout_seconds(self) -> int:
        return 600

    @property
    def input_types(self) -> dict[str, str]:
        return {"start_frame_path": "image"}

    @property
    def output_type(self) -> str:
        return "video"

    def health_check(self) -> bool:
        from workflow.adapters._health import check_fal_health
        return check_fal_health()

    def submit(self, config: dict) -> str:
        self._preflight()
        start_frame_path = config["start_frame_path"]
        prompt = merge_dialogue(config)
        output_dir = config["output_dir"]
        raw_duration = config.get("duration", 8)
        # LTX only accepts even durations: 6, 8, 10, etc. Snap up to nearest valid.
        valid_durations = [6, 8, 10, 12, 14, 16, 18, 20]
        duration = min(d for d in valid_durations if d >= raw_duration) if raw_duration <= 20 else 20
        # LTX only accepts 1080p, 1440p, 2160p — no 720p
        resolution = config.get("resolution", "1080p")
        if resolution not in ("1080p", "1440p", "2160p"):
            resolution = "1080p"
        fps = config.get("fps", 25)
        generate_audio = config.get("generate_audio", True)

        if not prompt:
            raise ValueError("'prompt' is required")
        if not os.path.exists(start_frame_path):
            raise FileNotFoundError(f"Start frame not found: {start_frame_path}")

        os.makedirs(output_dir, exist_ok=True)

        # Upload frame to Supabase for public URL
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        uid = uuid.uuid4().hex[:8]
        image_url = upload_to_supabase(IMAGE_BUCKET, start_frame_path, f"{ts}-{uid}-ltx-start.png")

        aspect_ratio = config.get("aspect_ratio", "9:16")

        arguments = {
            "image_url": image_url,
            "prompt": prompt,
            "duration": int(duration),
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "fps": int(fps),
            "generate_audio": generate_audio,
        }

        self.log_prompt(config, arguments, model=LTX_MODEL)

        request = fal_client.submit(LTX_MODEL, arguments=arguments)
        request_id = request.request_id

        self._jobs[request_id] = {
            "output_dir": output_dir,
            "output_filename": config.get("output_filename", "video_ltx.mp4"),
            "start_time": time.time(),
        }

        print(f"  [fal_ltx_v2] Submitted request: {request_id}", file=sys.stderr)
        return request_id

    def poll(self, job_id: str) -> tuple[Status, dict]:
        job_info = self._jobs.get(job_id, {})
        elapsed = time.time() - job_info.get("start_time", time.time())
        metadata: dict = {"elapsed_seconds": round(elapsed, 1)}

        try:
            status = fal_client.status(LTX_MODEL, job_id, with_logs=True)
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
                result = fal_client.result(LTX_MODEL, job_id)
                video_url = result["video"]["url"]
                output_dir = job_info.get("output_dir", ".")
                filename = job_info.get("output_filename", "video_ltx.mp4")
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
        filename = job_info.get("output_filename", "video_ltx.mp4")
        output_path = os.path.join(output_dir, filename)
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"Result not found: {output_path}")
        return output_path
