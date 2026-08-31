"""FAL Topaz Image Upscale adapter.

Upscales AI-generated images using Topaz's image upscaler via FAL.
Optimized for UGC anchor frames and starting frames — sharpens detail
and enhances faces while preserving composition.

Pricing: ~$0.04 per image (2x upscale).
"""

import os
import sys
import time

import fal_client
import requests
from dotenv import load_dotenv

from workflow.adapters.base import Adapter, Status
from workflow.adapters.registry import register
from workflow.adapters._supabase import upload_to_supabase, IMAGE_BUCKET

load_dotenv()

TOPAZ_IMAGE_MODEL = "fal-ai/topaz/upscale/image"

# Model presets
MODELS = {
    "high_fidelity_v2": "High Fidelity V2",
    "standard_v2": "Standard V2",
}

# Subject detection options
SUBJECT_DETECTION = {"all", "face", "none"}


def _download(url: str, dest: str) -> str:
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
    return dest


@register("fal_topaz_image_upscale")
class FalTopazImageUpscaleAdapter(Adapter):
    """Wraps FAL Topaz Image Upscaler for AI image upscaling.

    Config keys:
        image_path (str): Local path to image to upscale (required).
        output_dir (str): Directory for output image (required).
        output_filename (str): Filename (default "upscaled.jpg").
        model (str): "high_fidelity_v2" or "standard_v2" (default "high_fidelity_v2").
        upscale_factor (int): 1-4 (default 2).
        crop_to_fill (bool): Crop output to fill target dimensions (default False).
        output_format (str): "jpeg" or "png" (default "jpeg").
        subject_detection (str): "all", "face", or "none" (default "all").
        face_enhancement (bool): Enable face enhancement (default True).
        face_enhancement_creativity (int): 0-10 (default 0).
        face_enhancement_strength (float): 0.0-1.0 (default 0.8).
    """

    _jobs: dict[str, dict] = {}

    @property
    def timeout_seconds(self) -> int:
        return 300

    @property
    def input_types(self) -> dict[str, str]:
        return {"image_path": "image"}

    @property
    def output_type(self) -> str:
        return "image"

    def health_check(self) -> bool:
        from workflow.adapters._health import check_fal_health
        return check_fal_health()

    def submit(self, config: dict) -> str:
        self._preflight()
        image_path = config["image_path"]
        output_dir = config["output_dir"]

        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        os.makedirs(output_dir, exist_ok=True)

        # Upload image to Supabase for a public URL
        import uuid
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        uid = uuid.uuid4().hex[:8]
        ext = os.path.splitext(image_path)[1] or ".png"
        image_url = upload_to_supabase(IMAGE_BUCKET, image_path, f"{ts}-{uid}-topaz-img-input{ext}")

        # Build arguments
        model = config.get("model", "high_fidelity_v2")
        model_name = MODELS.get(model, "High Fidelity V2")

        upscale_factor = int(config.get("upscale_factor", 2))
        upscale_factor = max(1, min(4, upscale_factor))

        output_format = config.get("output_format", "jpeg")
        if output_format not in ("jpeg", "png"):
            output_format = "jpeg"

        subject_detection = config.get("subject_detection", "all")
        if subject_detection not in SUBJECT_DETECTION:
            subject_detection = "all"

        arguments: dict = {
            "image_url": image_url,
            "model": model_name,
            "upscale_factor": upscale_factor,
            "crop_to_fill": config.get("crop_to_fill", False),
            "output_format": output_format,
            "subject_detection": subject_detection,
            "face_enhancement": config.get("face_enhancement", True),
            "face_enhancement_creativity": int(config.get("face_enhancement_creativity", 0)),
            "face_enhancement_strength": float(config.get("face_enhancement_strength", 0.8)),
        }

        # Log prompt before submitting
        self.log_prompt(config, arguments, model=TOPAZ_IMAGE_MODEL)

        request = fal_client.submit(TOPAZ_IMAGE_MODEL, arguments=arguments)
        request_id = request.request_id

        # Determine output extension from format
        out_ext = ".jpg" if output_format == "jpeg" else ".png"
        default_filename = f"upscaled{out_ext}"

        self._jobs[request_id] = {
            "output_dir": output_dir,
            "output_filename": config.get("output_filename", default_filename),
            "start_time": time.time(),
        }

        print(f"  [topaz_img] Submitted image upscale: {request_id} ({model_name}, {upscale_factor}x)", file=sys.stderr)
        return request_id

    def poll(self, job_id: str) -> tuple[Status, dict]:
        job_info = self._jobs.get(job_id, {})
        elapsed = time.time() - job_info.get("start_time", time.time())
        metadata: dict = {"elapsed_seconds": round(elapsed, 1)}

        try:
            status = fal_client.status(TOPAZ_IMAGE_MODEL, job_id, with_logs=True)
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
                result = fal_client.result(TOPAZ_IMAGE_MODEL, job_id)
                image_url = result["image"]["url"]
                output_dir = job_info.get("output_dir", ".")
                filename = job_info.get("output_filename", "upscaled.jpg")
                output_path = os.path.join(output_dir, filename)
                _download(image_url, output_path)
                size_kb = os.path.getsize(output_path) / 1024
                print(f"  [topaz_img] Saved: {output_path} ({size_kb:.0f} KB)", file=sys.stderr)
                metadata["progress"] = 1.0
                metadata["output"] = output_path
                metadata["result_url"] = image_url
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
        filename = job_info.get("output_filename", "upscaled.jpg")
        output_path = os.path.join(output_dir, filename)
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"Result not found: {output_path}")
        return output_path
