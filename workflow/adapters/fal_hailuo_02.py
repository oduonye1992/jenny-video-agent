"""FAL Hailuo 02 (MiniMax) image-to-video adapter.

Budget-friendly video generation with great human motion.
Standard: $0.045/sec at 768p, $0.017/sec at 512p (6 or 10s).
Pro: $0.08/sec at 1080p (6 or 10s).
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

# Endpoints by tier
HAILUO_MODELS = {
    "pro": "fal-ai/minimax/hailuo-02/pro/image-to-video",
    "standard": "fal-ai/minimax/hailuo-02/standard/image-to-video",
}


def _download(url: str, dest: str) -> str:
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return dest


@register("fal_hailuo_02")
class FalHailuoAdapter(Adapter):
    """Wraps FAL Hailuo 02 (MiniMax) image-to-video generation.

    Config keys:
        start_frame_path (str): Local path to start frame image (required).
        prompt (str): Motion/scene prompt (required).
        output_dir (str): Directory for output video (required).
        tier (str): "pro" (1080p) or "standard" (768p/512p) (default "standard").
        duration (int): 6 or 10 seconds (default 10).
        prompt_optimizer (bool): Auto-enhance prompt (default True).
        end_frame_path (str): Optional end frame for interpolation.
        output_filename (str): Output filename (default "video_hailuo.mp4").
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

    def _get_model(self, tier: str) -> str:
        return HAILUO_MODELS.get(tier, HAILUO_MODELS["standard"])

    def health_check(self) -> bool:
        from workflow.adapters._health import check_fal_health
        return check_fal_health()

    def submit(self, config: dict) -> str:
        self._preflight()
        start_frame_path = config["start_frame_path"]
        prompt = merge_dialogue(config)
        output_dir = config["output_dir"]
        tier = config.get("tier", "standard")
        duration = config.get("duration", 10)
        prompt_optimizer = config.get("prompt_optimizer", True)
        end_frame_path = config.get("end_frame_path")

        if not prompt:
            raise ValueError("'prompt' is required")
        if not os.path.exists(start_frame_path):
            raise FileNotFoundError(f"Start frame not found: {start_frame_path}")

        os.makedirs(output_dir, exist_ok=True)

        # Upload frames to Supabase for public URLs
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        uid = uuid.uuid4().hex[:8]
        image_url = upload_to_supabase(IMAGE_BUCKET, start_frame_path, f"{ts}-{uid}-hailuo-start.png")

        model = self._get_model(tier)

        arguments = {
            "prompt": prompt,
            "image_url": image_url,
            "prompt_optimizer": prompt_optimizer,
        }

        # Duration supported on standard tier
        if tier == "standard":
            arguments["duration"] = int(duration)

        if end_frame_path:
            if not os.path.exists(end_frame_path):
                raise FileNotFoundError(f"End frame not found: {end_frame_path}")
            end_url = upload_to_supabase(IMAGE_BUCKET, end_frame_path, f"{ts}-{uid}-hailuo-end.png")
            arguments["end_image_url"] = end_url

        self.log_prompt(config, arguments, model=model)

        request = fal_client.submit(model, arguments=arguments)
        request_id = request.request_id

        self._jobs[request_id] = {
            "output_dir": output_dir,
            "output_filename": config.get("output_filename", "video_hailuo.mp4"),
            "model": model,
            "start_time": time.time(),
        }

        print(f"  [fal_hailuo_02] Submitted request: {request_id} (tier={tier})", file=sys.stderr)
        return request_id

    def poll(self, job_id: str) -> tuple[Status, dict]:
        job_info = self._jobs.get(job_id, {})
        elapsed = time.time() - job_info.get("start_time", time.time())
        model = job_info.get("model", HAILUO_MODELS["standard"])
        metadata: dict = {"elapsed_seconds": round(elapsed, 1)}

        try:
            status = fal_client.status(model, job_id, with_logs=True)
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
                result = fal_client.result(model, job_id)
                video_url = result["video"]["url"]
                output_dir = job_info.get("output_dir", ".")
                filename = job_info.get("output_filename", "video_hailuo.mp4")
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
        filename = job_info.get("output_filename", "video_hailuo.mp4")
        output_path = os.path.join(output_dir, filename)
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"Result not found: {output_path}")
        return output_path
