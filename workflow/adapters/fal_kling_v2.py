"""FAL Kling v2.6 Pro image-to-video adapter.

Supports two modes:
  - Standard image-to-video (default)
  - Motion control (when video_url is provided)
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

KLING26_I2V_MODEL = "fal-ai/kling-video/v2.6/pro/image-to-video"
KLING26_MC_MODEL = "fal-ai/kling-video/v2.6/pro/motion-control"

VIDEO_BUCKET = "reference_video_clips"


def _download(url: str, dest: str) -> str:
    """Download a file from URL to local path."""
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return dest


@register("fal_kling_v2")
class FalKling26Adapter(Adapter):
    """Wraps FAL Kling v2.6 Pro for image-to-video and motion control.

    Config keys (image-to-video mode):
        start_frame_path (str): Local path to start frame image (required).
        prompt (str): Motion prompt (required).
        output_dir (str): Directory for output video (required).
        duration (str): Video duration, "5" or "10" (default "10").
        aspect_ratio (str): "16:9", "9:16", or "1:1" (default "9:16").
        negative_prompt (str): Negative prompt (default "blur, distort, and low quality").
        cfg_scale (float): 0-1 (default 0.5).
        generate_audio (bool): Whether to generate native audio (default True).
        end_frame_path (str): Optional end frame for interpolation.

    Config keys (motion control mode -- activated when video_url or video_path is set):
        start_frame_path (str): Character frame (required).
        video_url (str): Public URL of reference video clip.
        video_path (str): Local path to reference video clip (uploaded to Supabase).
        character_orientation (str): "image" or "video" (default "image").
        prompt (str): Optional motion prompt.
        output_dir (str): Directory for output video (required).
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
        output_dir = config["output_dir"]

        if not os.path.exists(start_frame_path):
            raise FileNotFoundError(f"Start frame not found: {start_frame_path}")
        os.makedirs(output_dir, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        uid = uuid.uuid4().hex[:8]

        # Determine mode: motion control vs standard i2v
        video_url = config.get("video_url")
        video_path = config.get("video_path")
        is_motion_control = bool(video_url or video_path)

        if is_motion_control:
            return self._submit_motion_control(config, start_frame_path, ts, uid, output_dir, video_url, video_path)
        else:
            return self._submit_i2v(config, start_frame_path, ts, uid, output_dir)

    def _submit_i2v(self, config: dict, start_frame_path: str, ts: str, uid: str, output_dir: str) -> str:
        """Standard image-to-video submission."""
        prompt = merge_dialogue(config, adapter_name="fal_kling_v2")
        end_frame_path = config.get("end_frame_path")
        raw_duration = config.get("duration", "10")
        # Kling 2.6 only accepts "5" or "10" — snap to nearest valid value
        dur_num = int(str(raw_duration).strip())
        duration = "5" if dur_num <= 7 else "10"
        aspect_ratio = config.get("aspect_ratio", "9:16")
        negative_prompt = config.get("negative_prompt", "blur, distort, and low quality")
        cfg_scale = config.get("cfg_scale", 0.5)
        generate_audio = config.get("generate_audio", True)

        start_url = upload_to_supabase(IMAGE_BUCKET, start_frame_path, f"{ts}-{uid}-start_frame.png")

        end_url = None
        if end_frame_path:
            if not os.path.exists(end_frame_path):
                raise FileNotFoundError(f"End frame not found: {end_frame_path}")
            end_url = upload_to_supabase(IMAGE_BUCKET, end_frame_path, f"{ts}-{uid}-end_frame.png")

        arguments = {
            "prompt": prompt,
            "start_image_url": start_url,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "negative_prompt": negative_prompt,
            "cfg_scale": cfg_scale,
            "generate_audio": generate_audio,
        }
        if end_url:
            arguments["end_image_url"] = end_url

        model = KLING26_I2V_MODEL
        self.log_prompt(config, arguments, model=model)

        request = fal_client.submit(model, arguments=arguments)
        request_id = request.request_id

        self._jobs[request_id] = {
            "output_dir": output_dir,
            "output_filename": config.get("output_filename", "scene_video.mp4"),
            "start_time": time.time(),
            "model": model,
        }

        print(f"  [fal_kling_v2] Submitted i2v request: {request_id}", file=sys.stderr)
        return request_id

    def _submit_motion_control(
        self, config: dict, start_frame_path: str, ts: str, uid: str, output_dir: str,
        video_url: str | None, video_path: str | None,
    ) -> str:
        """Motion control submission."""
        prompt = config.get("prompt", "")
        character_orientation = config.get("character_orientation", "image")

        image_url = upload_to_supabase(IMAGE_BUCKET, start_frame_path, f"{ts}-{uid}-character_frame.png")

        if not video_url and video_path:
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"Video not found: {video_path}")
            video_url = upload_to_supabase(VIDEO_BUCKET, video_path, f"{ts}-{uid}-reference_clip.mp4")

        if not video_url:
            raise ValueError("Motion control requires 'video_url' or 'video_path'")

        arguments = {
            "image_url": image_url,
            "video_url": video_url,
            "character_orientation": character_orientation,
        }
        if prompt:
            arguments["prompt"] = prompt

        model = KLING26_MC_MODEL
        self.log_prompt(config, arguments, model=model)

        request = fal_client.submit(model, arguments=arguments)
        request_id = request.request_id

        self._jobs[request_id] = {
            "output_dir": output_dir,
            "output_filename": config.get("output_filename", "motion_video.mp4"),
            "start_time": time.time(),
            "model": model,
        }

        print(f"  [fal_kling_v2] Submitted motion control request: {request_id}", file=sys.stderr)
        return request_id

    def poll(self, job_id: str) -> tuple[Status, dict]:
        job_info = self._jobs.get(job_id, {})
        model = job_info.get("model", KLING26_I2V_MODEL)
        elapsed = time.time() - job_info.get("start_time", time.time())
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
                filename = job_info.get("output_filename", "scene_video.mp4")
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
        filename = job_info.get("output_filename", "scene_video.mp4")
        output_path = os.path.join(output_dir, filename)
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"Result not found: {output_path}")
        return output_path
