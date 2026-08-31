"""FAL Veo 3.1 Fast text-to-video adapter.

Uses fal-ai/veo3.1/fast/text-to-video via the FAL API.
No start frame required — pure text-to-video generation.

Pricing (fast tier):
  720p/1080p without audio: $0.10/sec
  720p/1080p with audio:    $0.15/sec
  4K without audio:         $0.30/sec
  4K with audio:            $0.35/sec
"""

import os
import sys
import time

import fal_client
import requests
from dotenv import load_dotenv

from workflow.adapters.base import Adapter, Status
from workflow.adapters.registry import register
from workflow.adapters._prompt import merge_dialogue

load_dotenv()

VEO_T2V_MODEL = "fal-ai/veo3.1/fast/text-to-video"

VALID_DURATIONS = {"4s", "6s", "8s"}
VALID_RESOLUTIONS = {"720p", "1080p", "4k"}


def _download(url: str, dest: str) -> str:
    """Download a file from URL to local path."""
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return dest


@register("fal_veo_v3_t2v")
class FalVeoT2VAdapter(Adapter):
    """Wraps FAL Veo 3.1 Fast for text-to-video generation (no start frame).

    Config keys:
        prompt (str): Video generation prompt (required).
        output_dir (str): Directory for output video (required).
        duration (str): "4s", "6s", or "8s" (default "8s").
        aspect_ratio (str): "16:9", "9:16", or "auto" (default "auto").
        resolution (str): "720p", "1080p", or "4k" (default "720p").
        negative_prompt (str): Negative prompt (optional).
        generate_audio (bool): Whether to generate audio (default True).
        seed (int): Random seed (optional).
        output_filename (str): Output filename (default "video_veo.mp4").
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
        return {}  # No image input — text-to-video

    @property
    def output_type(self) -> str:
        return "video"

    def submit(self, config: dict) -> str:
        self._preflight()
        prompt = merge_dialogue(config)
        output_dir = config["output_dir"]

        if not prompt:
            raise ValueError("'prompt' is required")

        os.makedirs(output_dir, exist_ok=True)

        # Normalize duration
        raw_duration = str(config.get("duration", "8s"))
        if not raw_duration.endswith("s"):
            raw_duration = f"{raw_duration}s"
        duration = raw_duration if raw_duration in VALID_DURATIONS else "8s"

        resolution = config.get("resolution", "720p")
        if resolution not in VALID_RESOLUTIONS:
            resolution = "720p"

        aspect_ratio = config.get("aspect_ratio", "auto")
        generate_audio = config.get("generate_audio", True)

        arguments: dict = {
            "prompt": prompt,
            "duration": duration,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "generate_audio": generate_audio,
        }

        negative_prompt = config.get("negative_prompt")
        if negative_prompt:
            arguments["negative_prompt"] = negative_prompt

        seed = config.get("seed")
        if seed is not None:
            arguments["seed"] = int(seed)

        self.log_prompt(config, arguments, model=VEO_T2V_MODEL)

        request = fal_client.submit(VEO_T2V_MODEL, arguments=arguments)
        request_id = request.request_id

        self._jobs[request_id] = {
            "output_dir": output_dir,
            "output_filename": config.get("output_filename", "video_veo.mp4"),
            "start_time": time.time(),
        }

        print(f"  [fal_veo_v3_t2v] Submitted request: {request_id}", file=sys.stderr)
        return request_id

    def poll(self, job_id: str) -> tuple[Status, dict]:
        job_info = self._jobs.get(job_id, {})
        elapsed = time.time() - job_info.get("start_time", time.time())
        metadata: dict = {"elapsed_seconds": round(elapsed, 1)}

        try:
            status = fal_client.status(VEO_T2V_MODEL, job_id, with_logs=True)
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
                result = fal_client.result(VEO_T2V_MODEL, job_id)
                video_url = result["video"]["url"]
                output_dir = job_info.get("output_dir", ".")
                filename = job_info.get("output_filename", "video_veo.mp4")
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
        filename = job_info.get("output_filename", "video_veo.mp4")
        output_path = os.path.join(output_dir, filename)
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"Result not found: {output_path}")
        return output_path
