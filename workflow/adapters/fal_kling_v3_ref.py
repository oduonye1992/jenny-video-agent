"""FAL Kling O1 reference-to-video adapter.

Uses character elements for face locking WITHOUT a start frame.
The model generates the scene from text while maintaining face consistency
from the reference element.
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

KLING_O1_REF_MODEL = "fal-ai/kling-video/o1/reference-to-video"


def _download(url: str, dest: str) -> str:
    """Download a file from URL to local path."""
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return dest


@register("fal_kling_v3_ref")
class FalKlingRefAdapter(Adapter):
    """Wraps FAL Kling O1 reference-to-video generation.

    Text-to-video with character face locking via elements.
    No start frame required — the model builds the scene from the prompt
    while maintaining face identity from the reference element.

    Config keys:
        prompt (str): Video prompt with @Element1 referencing the character (required).
        character_ref_frame_path (str): Local path to face reference image (required).
        output_dir (str): Directory for output video (required).
        duration (str): Video duration, "3"-"10" (default "10").
        aspect_ratio (str): "16:9", "9:16", or "1:1" (default "9:16").
        elements (list): Explicit elements (overrides character_ref_frame_path).
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
        return {"character_ref_frame_path": "image"}

    @property
    def output_type(self) -> str:
        return "video"

    def submit(self, config: dict) -> str:
        self._preflight()

        prompt = merge_dialogue(config)
        if not prompt:
            raise ValueError("Must provide 'prompt'")

        output_dir = config["output_dir"]
        duration = str(config.get("duration", "10"))
        aspect_ratio = config.get("aspect_ratio", "9:16")
        elements = config.get("elements")

        # Build elements from character_ref_frame_path if no explicit elements
        if not elements:
            ref_path = config.get("character_ref_frame_path")
            if not ref_path:
                raise ValueError("Must provide 'character_ref_frame_path' or 'elements'")
            if not os.path.exists(ref_path):
                raise FileNotFoundError(f"Reference frame not found: {ref_path}")
            elements = [{"frontal_image_path": ref_path, "reference_image_paths": [ref_path]}]

        os.makedirs(output_dir, exist_ok=True)

        # Upload element images to Supabase
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        uid = uuid.uuid4().hex[:8]

        for i, elem in enumerate(elements):
            if "frontal_image_path" in elem:
                url = upload_to_supabase(
                    IMAGE_BUCKET, elem["frontal_image_path"], f"{ts}-{uid}-element{i}-frontal.png"
                )
                elem["frontal_image_url"] = url
                del elem["frontal_image_path"]
            if "reference_image_paths" in elem:
                urls = []
                for j, path in enumerate(elem["reference_image_paths"]):
                    url = upload_to_supabase(
                        IMAGE_BUCKET, path, f"{ts}-{uid}-element{i}-ref{j}.png"
                    )
                    urls.append(url)
                elem["reference_image_urls"] = urls
                del elem["reference_image_paths"]

        negative_prompt = config.get("negative_prompt", "blur, distort, and low quality")
        cfg_scale = config.get("cfg_scale", 0.5)
        generate_audio = config.get("generate_audio", True)

        # Build FAL arguments — no start_image_url
        arguments = {
            "prompt": prompt,
            "elements": elements,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "negative_prompt": negative_prompt,
            "cfg_scale": cfg_scale,
            "generate_audio": generate_audio,
        }

        # Log prompt before submitting
        self.log_prompt(config, arguments, model=KLING_O1_REF_MODEL)

        # Submit to FAL
        request = fal_client.submit(KLING_O1_REF_MODEL, arguments=arguments)
        request_id = request.request_id

        self._jobs[request_id] = {
            "output_dir": output_dir,
            "output_filename": config.get("output_filename", "scene_video.mp4"),
            "start_time": time.time(),
        }

        print(f"  [fal_kling_v3_ref] Submitted reference-to-video ({duration}s): {request_id}", file=sys.stderr)
        return request_id

    def poll(self, job_id: str) -> tuple[Status, dict]:
        job_info = self._jobs.get(job_id, {})
        elapsed = time.time() - job_info.get("start_time", time.time())
        metadata: dict = {"elapsed_seconds": round(elapsed, 1)}

        try:
            status = fal_client.status(KLING_O1_REF_MODEL, job_id, with_logs=True)
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
                result = fal_client.result(KLING_O1_REF_MODEL, job_id)
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
