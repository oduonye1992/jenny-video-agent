"""OpenAI Sora 2 character extraction adapter.

Creates a reusable Sora character ID from a video clip.
The character ID can then be passed to openai_sora_t2v or openai_sora_i2v
via character_ids to maintain consistent character identity across shots.

Uses raw HTTP to POST /v1/video_characters (no SDK namespace exists yet).
Pricing: included in Sora 2 usage (free character creation).
"""

import json
import os
import sys
import time

import httpx
from dotenv import load_dotenv

from workflow.adapters.base import Adapter, Status
from workflow.adapters.registry import register

load_dotenv()

OPENAI_BASE_URL = "https://api.openai.com/v1"


@register("openai_sora_character")
class OpenAISoraCharacterAdapter(Adapter):
    """Extract a reusable character ID from a video clip via OpenAI API.

    Config keys:
        video_path (str): Local path to a video clip (required). Min 720p, 1-4s recommended.
        name (str): Character name (required, 1-80 chars).
        output_dir (str): Directory to save the character.json file (required).
        output_filename (str): Filename for the character ID JSON (default "character.json").
    """

    _jobs: dict[str, dict] = {}

    def health_check(self) -> bool:
        from workflow.adapters._health import check_openai_health
        return check_openai_health()

    @property
    def timeout_seconds(self) -> int:
        return 300

    @property
    def input_types(self) -> dict[str, str]:
        return {"video_path": "video"}

    @property
    def output_type(self) -> str:
        return "json"

    def submit(self, config: dict) -> str:
        self._preflight()

        video_path = config.get("video_path")
        name = config.get("name")

        if not video_path:
            raise ValueError("'video_path' is required — path to the video clip")
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")
        if not name:
            raise ValueError("'name' is required — character name (1-80 chars)")
        if len(name) > 80:
            raise ValueError(f"'name' must be 1-80 chars, got {len(name)}")

        output_dir = config["output_dir"]
        os.makedirs(output_dir, exist_ok=True)

        # Read video bytes
        with open(video_path, "rb") as f:
            video_bytes = f.read()

        filename = os.path.basename(video_path)

        # Build payload for logging
        payload = {
            "video_path": video_path,
            "name": name,
            "endpoint": f"{OPENAI_BASE_URL}/video_characters",
        }
        self.log_prompt(config, payload, model="sora-2")

        # Submit via raw HTTP — no SDK namespace for characters yet
        api_key = os.environ["OPENAI_API_KEY"]
        response = httpx.post(
            f"{OPENAI_BASE_URL}/video_characters",
            headers={"Authorization": f"Bearer {api_key}"},
            files={"video": (filename, video_bytes, "video/mp4")},
            data={"name": name},
            timeout=60.0,
        )
        response.raise_for_status()
        result = response.json()

        # The response may be sync (id + completed/no status) or async (id + status)
        character_id = result.get("id", "")
        status_str = result.get("status", "")

        # Determine if already completed
        is_completed = (
            not status_str
            or status_str == "completed"
        )

        job_key = character_id or result.get("job_id", f"char_{int(time.time())}")

        self._jobs[job_key] = {
            "output_dir": output_dir,
            "output_filename": config.get("output_filename", "character.json"),
            "name": name,
            "start_time": time.time(),
            "completed": is_completed,
            "result": result,
        }

        print(f"  [openai_sora_character] Submitted: {job_key} (completed={is_completed})", file=sys.stderr)
        return job_key

    def poll(self, job_id: str) -> tuple[Status, dict]:
        job_info = self._jobs.get(job_id, {})
        elapsed = time.time() - job_info.get("start_time", time.time())
        metadata: dict = {"elapsed_seconds": round(elapsed, 1)}

        # If already completed at submit time, save and return
        if job_info.get("completed"):
            return self._save_character(job_id, job_info, metadata)

        # Otherwise poll the API
        try:
            api_key = os.environ["OPENAI_API_KEY"]
            response = httpx.get(
                f"{OPENAI_BASE_URL}/video_characters/{job_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30.0,
            )
            response.raise_for_status()
            result = response.json()
        except Exception as exc:
            metadata["error"] = str(exc)
            return Status.RUNNING, metadata

        status_str = result.get("status", "")

        if status_str in ("queued", "pending"):
            metadata["progress"] = 0.0
            return Status.PENDING, metadata
        elif status_str == "in_progress":
            metadata["progress"] = 0.5
            return Status.RUNNING, metadata
        elif status_str == "completed" or not status_str:
            job_info["result"] = result
            return self._save_character(job_id, job_info, metadata)
        elif status_str == "failed":
            error_msg = result.get("error", "Unknown error")
            metadata["error"] = str(error_msg)
            return Status.FAILED, metadata
        else:
            metadata["error"] = f"Unexpected status: {status_str}"
            return Status.FAILED, metadata

    def _save_character(self, job_id: str, job_info: dict, metadata: dict) -> tuple[Status, dict]:
        """Save the character result to JSON and return COMPLETED status."""
        try:
            result = job_info.get("result", {})
            character_id = result.get("id", job_id)

            output_dir = job_info.get("output_dir", ".")
            filename = job_info.get("output_filename", "character.json")
            output_path = os.path.join(output_dir, filename)

            with open(output_path, "w") as f:
                json.dump({
                    "character_id": character_id,
                    "name": job_info.get("name", ""),
                    "result": result,
                }, f, indent=2)

            metadata["progress"] = 1.0
            metadata["output"] = output_path
            metadata["character_id"] = character_id
            return Status.COMPLETED, metadata
        except Exception as exc:
            metadata["error"] = f"Failed to save result: {exc}"
            return Status.FAILED, metadata

    def get_result(self, job_id: str) -> str:
        job_info = self._jobs.get(job_id, {})
        output_dir = job_info.get("output_dir", ".")
        filename = job_info.get("output_filename", "character.json")
        output_path = os.path.join(output_dir, filename)
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"Result not found: {output_path}")
        return output_path


def list_characters() -> list[dict]:
    """List existing Sora characters on the account. Returns list of {id, name} dicts.

    Uses GET /v1/video_characters — may return 404 if endpoint not available yet.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    response = httpx.get(
        f"{OPENAI_BASE_URL}/video_characters",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()

    # Handle both list response and paginated response
    items = data if isinstance(data, list) else data.get("data", [])
    return [{"id": item.get("id", ""), "name": item.get("name", "")} for item in items]
