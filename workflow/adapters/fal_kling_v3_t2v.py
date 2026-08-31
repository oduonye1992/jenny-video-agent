"""FAL Kling v3.0 text-to-video adapter.

Uses fal-ai/kling-video/v3/pro/text-to-video via the FAL API.
No start frame required — pure text-to-video generation.
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

KLING3_T2V_MODEL = "fal-ai/kling-video/v3/pro/text-to-video"


def _download(url: str, dest: str) -> str:
    """Download a file from URL to local path."""
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return dest


@register("fal_kling_v3_t2v")
class FalKlingT2VAdapter(Adapter):
    """Wraps FAL Kling v3.0 for text-to-video generation (no start frame).

    Config keys:
        prompt (str): Motion prompt (required unless multi_prompt given).
        output_dir (str): Directory for output video (required).
        duration (str): Video duration, "5" or "10" (default "10"). Ignored when multi_prompt is used.
        aspect_ratio (str): "16:9", "9:16", or "1:1" (default "9:16").
        negative_prompt (str): Negative prompt (default "blur, distort, and low quality").
        cfg_scale (float): 0-1 (default 0.5).
        generate_audio (bool): Whether to generate audio (default True).
        multi_prompt (list): Optional multi-shot prompts — up to 6 shots, each with
            {"text": "<prompt>", "duration": <seconds>}, totaling up to 15s.
            Mutually exclusive with prompt. Sets shot_type="customize" automatically.
        output_filename (str): Output filename (default "video_kling.mp4").
    """

    _jobs: dict[str, dict] = {}

    def health_check(self) -> bool:
        from workflow.adapters._health import check_fal_health
        return check_fal_health()

    @property
    def timeout_seconds(self) -> int:
        return 900

    @property
    def input_types(self) -> dict[str, str]:
        return {}  # No image input — text-to-video

    @property
    def output_type(self) -> str:
        return "video"

    def submit(self, config: dict) -> str:
        self._preflight()
        multi_prompt = config.get("multi_prompt")

        # Validate multi_prompt BEFORE merge_dialogue
        if config.get("prompt") and multi_prompt:
            raise ValueError("Cannot provide both 'prompt' and 'multi_prompt' — they are mutually exclusive")
        if multi_prompt:
            if not isinstance(multi_prompt, list) or len(multi_prompt) < 1:
                raise ValueError("'multi_prompt' must be a non-empty list")
            if len(multi_prompt) > 6:
                raise ValueError(f"'multi_prompt' supports up to 6 shots, got {len(multi_prompt)}")
            total_duration = 0
            for i, shot in enumerate(multi_prompt):
                if "text" not in shot or "duration" not in shot:
                    raise ValueError(f"multi_prompt[{i}] must have 'text' and 'duration' keys")
                if len(shot["text"]) > 512:
                    raise ValueError(
                        f"multi_prompt[{i}] text is {len(shot['text'])} chars, max is 512. "
                        f"Trim the prompt — tighten action beats, compress dialogue delivery notes."
                    )
                total_duration += shot["duration"]
            if total_duration > 15:
                raise ValueError(f"multi_prompt total duration is {total_duration}s, max is 15s")

        # merge_dialogue returns "" for multi-shot mode
        prompt = merge_dialogue(config)
        output_dir = config["output_dir"]
        duration = config.get("duration", "10")
        aspect_ratio = config.get("aspect_ratio", "9:16")
        negative_prompt = config.get("negative_prompt", "blur, distort, and low quality")
        cfg_scale = config.get("cfg_scale", 0.5)
        generate_audio = config.get("generate_audio", True)

        if not prompt and not multi_prompt:
            raise ValueError("Must provide 'prompt' or 'multi_prompt'")

        os.makedirs(output_dir, exist_ok=True)

        arguments = {
            "aspect_ratio": aspect_ratio,
            "negative_prompt": negative_prompt,
            "cfg_scale": cfg_scale,
            "generate_audio": generate_audio,
        }

        if multi_prompt:
            arguments["multi_prompt"] = multi_prompt
            arguments["shot_type"] = "customize"
        elif prompt:
            arguments["prompt"] = prompt
            arguments["duration"] = duration

        self.log_prompt(config, arguments, model=KLING3_T2V_MODEL)

        request = fal_client.submit(KLING3_T2V_MODEL, arguments=arguments)
        request_id = request.request_id

        self._jobs[request_id] = {
            "output_dir": output_dir,
            "output_filename": config.get("output_filename", "video_kling.mp4"),
            "start_time": time.time(),
        }

        if multi_prompt:
            total_dur = sum(s["duration"] for s in multi_prompt)
            print(f"  [fal_kling_v3_t2v] Submitted multi-shot request ({len(multi_prompt)} shots, {total_dur}s): {request_id}", file=sys.stderr)
        else:
            print(f"  [fal_kling_v3_t2v] Submitted request ({duration}s): {request_id}", file=sys.stderr)
        return request_id

    def poll(self, job_id: str) -> tuple[Status, dict]:
        job_info = self._jobs.get(job_id, {})
        elapsed = time.time() - job_info.get("start_time", time.time())
        metadata: dict = {"elapsed_seconds": round(elapsed, 1)}

        try:
            status = fal_client.status(KLING3_T2V_MODEL, job_id, with_logs=True)
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
                result = fal_client.result(KLING3_T2V_MODEL, job_id)
                video_url = result["video"]["url"]
                output_dir = job_info.get("output_dir", ".")
                filename = job_info.get("output_filename", "video_kling.mp4")
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
        filename = job_info.get("output_filename", "video_kling.mp4")
        output_path = os.path.join(output_dir, filename)
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"Result not found: {output_path}")
        return output_path
