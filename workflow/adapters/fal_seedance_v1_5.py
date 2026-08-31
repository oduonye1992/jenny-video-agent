"""FAL Seedance 1.5 Pro image-to-video adapter."""

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

SEEDANCE_MODEL = "fal-ai/bytedance/seedance/v1.5/pro/image-to-video"


def _download(url: str, dest: str) -> str:
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return dest


@register("fal_seedance_v1_5")
class FalSeedanceV15Adapter(Adapter):
    """Wraps FAL Seedance 1.5 Pro image-to-video generation.

    Config keys:
        start_frame_path (str): Local path to start frame image (required).
        prompt (str): Motion/action prompt (required).
        output_dir (str): Directory for output video (required).
        end_frame_path (str): Optional end frame for interpolation.
        duration (int): Video duration in seconds, 4-12 (default 8).
        aspect_ratio (str): "16:9", "9:16", "1:1", etc. (default "9:16").
        resolution (str): "480p" or "720p" (default "720p").
        generate_audio (bool): Whether to generate audio (default True).
        camera_fixed (bool): Lock camera in place (default False).
        seed (int): Seed for reproducibility (-1 for random).
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
        end_frame_path = config.get("end_frame_path")
        prompt = merge_dialogue(config)
        output_dir = config["output_dir"]
        duration = config.get("duration", 8)
        aspect_ratio = config.get("aspect_ratio", "9:16")
        resolution = config.get("resolution", "720p")
        generate_audio = config.get("generate_audio", True)
        camera_fixed = config.get("camera_fixed", False)
        seed = config.get("seed")

        if not prompt:
            raise ValueError("Must provide 'prompt'")

        if not os.path.exists(start_frame_path):
            raise FileNotFoundError(f"Start frame not found: {start_frame_path}")

        os.makedirs(output_dir, exist_ok=True)

        # Upload frames to Supabase
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        uid = uuid.uuid4().hex[:8]
        start_url = upload_to_supabase(IMAGE_BUCKET, start_frame_path, f"{ts}-{uid}-seedance15-start.png")

        end_url = None
        if end_frame_path:
            if not os.path.exists(end_frame_path):
                raise FileNotFoundError(f"End frame not found: {end_frame_path}")
            end_url = upload_to_supabase(IMAGE_BUCKET, end_frame_path, f"{ts}-{uid}-seedance15-end.png")

        arguments = {
            "image_url": start_url,
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "generate_audio": generate_audio,
            "camera_fixed": camera_fixed,
        }

        if end_url:
            arguments["end_image_url"] = end_url
        if seed is not None:
            arguments["seed"] = seed

        self.log_prompt(config, arguments, model=SEEDANCE_MODEL)

        request = fal_client.submit(SEEDANCE_MODEL, arguments=arguments)
        request_id = request.request_id

        self._jobs[request_id] = {
            "output_dir": output_dir,
            "output_filename": config.get("output_filename", "seedance_video.mp4"),
            "start_time": time.time(),
        }

        print(f"  [fal_seedance_v1_5] Submitted request: {request_id}", file=sys.stderr)
        return request_id

    def poll(self, job_id: str) -> tuple[Status, dict]:
        job_info = self._jobs.get(job_id, {})
        elapsed = time.time() - job_info.get("start_time", time.time())
        metadata: dict = {"elapsed_seconds": round(elapsed, 1)}

        try:
            status = fal_client.status(SEEDANCE_MODEL, job_id, with_logs=True)
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
                result = fal_client.result(SEEDANCE_MODEL, job_id)
                video_url = result["video"]["url"]
                output_dir = job_info.get("output_dir", ".")
                filename = job_info.get("output_filename", "seedance_video.mp4")
                output_path = os.path.join(output_dir, filename)
                _download(video_url, output_path)
                metadata["progress"] = 1.0
                metadata["output"] = output_path
                metadata["result_url"] = video_url
                if "seed" in result:
                    metadata["seed"] = result["seed"]
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
        filename = job_info.get("output_filename", "seedance_video.mp4")
        output_path = os.path.join(output_dir, filename)
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"Result not found: {output_path}")
        return output_path
