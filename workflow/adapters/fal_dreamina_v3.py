"""FAL Dreamina v3.1 text-to-image adapter."""

import os
import sys
import time

import fal_client
import requests
from dotenv import load_dotenv

from workflow.adapters.base import Adapter, Status
from workflow.adapters.registry import register

load_dotenv()

DREAMINA_MODEL = "fal-ai/dreamina/v3.1"


def _download(url: str, dest: str) -> str:
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return dest


@register("fal_dreamina_v3")
class FalDreaminaAdapter(Adapter):
    """Wraps FAL Dreamina v3.1 for text-to-image generation.

    Submit, poll, and download the result. Although the FAL API is async
    (submit/status/result), the adapter presents the standard interface.

    Config keys:
        prompt (str): Image generation prompt (required).
        output_path (str): Where to save the generated image (required).
        aspect_ratio (str): Image aspect ratio (default "9:16").
        negative_prompt (str): Optional negative prompt.
    """

    _jobs: dict[str, dict] = {}

    @property
    def timeout_seconds(self) -> int:
        return 120

    @property
    def input_types(self) -> dict[str, str]:
        return {}

    @property
    def output_type(self) -> str:
        return "image"

    def health_check(self) -> bool:
        from workflow.adapters._health import check_fal_health
        return check_fal_health()

    def submit(self, config: dict) -> str:
        self._preflight()
        prompt = config["prompt"]
        output_path = config["output_path"]
        aspect_ratio = config.get("aspect_ratio", "9:16")
        negative_prompt = config.get("negative_prompt", "")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        arguments: dict = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
        }
        if negative_prompt:
            arguments["negative_prompt"] = negative_prompt

        self.log_prompt(config, arguments, model=DREAMINA_MODEL)

        request = fal_client.submit(DREAMINA_MODEL, arguments=arguments)
        request_id = request.request_id

        self._jobs[request_id] = {
            "output_path": output_path,
            "start_time": time.time(),
        }

        print(f"  [fal_dreamina_v3] Submitted request: {request_id}", file=sys.stderr)
        return request_id

    def poll(self, job_id: str) -> tuple[Status, dict]:
        job_info = self._jobs.get(job_id, {})
        elapsed = time.time() - job_info.get("start_time", time.time())
        metadata: dict = {"elapsed_seconds": round(elapsed, 1)}

        try:
            status = fal_client.status(DREAMINA_MODEL, job_id, with_logs=True)
        except Exception as exc:
            metadata["error"] = str(exc)
            return Status.RUNNING, metadata

        if isinstance(status, fal_client.Queued):
            metadata["progress"] = 0.0
            return Status.PENDING, metadata

        elif isinstance(status, fal_client.InProgress):
            metadata["progress"] = 0.5
            return Status.RUNNING, metadata

        elif isinstance(status, fal_client.Completed):
            try:
                result = fal_client.result(DREAMINA_MODEL, job_id)
                # Dreamina returns images in result["images"][0]["url"]
                images = result.get("images", [])
                if not images:
                    metadata["error"] = "No images in result"
                    return Status.FAILED, metadata

                image_url = images[0]["url"]
                output_path = job_info.get("output_path", "output.png")
                _download(image_url, output_path)
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
        output_path = job_info.get("output_path", "output.png")
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"Result not found: {output_path}")
        return output_path
