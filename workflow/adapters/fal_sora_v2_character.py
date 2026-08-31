"""FAL Sora 2 character extraction adapter.

Creates a reusable Sora character ID from a video clip.
The character ID can then be passed to fal_sora_v2 or fal_sora_v2_t2v via character_ids
to maintain consistent character identity across shots.

Uses fal-ai/sora-2/characters via the FAL API.
Pricing: included in Sora 2 usage.
"""

import json
import os
import sys
import time
import uuid
from datetime import datetime

import fal_client
from dotenv import load_dotenv

from workflow.adapters.base import Adapter, Status
from workflow.adapters.registry import register
from workflow.adapters._supabase import upload_to_supabase, VIDEO_BUCKET

load_dotenv()

SORA_CHARACTER_MODEL = "fal-ai/sora-2/characters"


@register("fal_sora_v2_character")
class FalSoraCharacterAdapter(Adapter):
    """Extract a reusable character ID from a video clip.

    Config keys:
        video_path (str): Local path to a video clip (required). Min 720p, 1-4s recommended.
            Clips over 4s are auto-trimmed to the first 4s by the API.
        name (str): Character name (required, 1-80 chars). Reference this name in prompts.
        output_dir (str): Directory to save the character_id file (required).
        output_filename (str): Filename for the character ID JSON (default "character.json").
    """

    _jobs: dict[str, dict] = {}

    def health_check(self) -> bool:
        from workflow.adapters._health import check_fal_health
        return check_fal_health()

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
        if not name:
            raise ValueError("'name' is required — character name (1-80 chars)")
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")

        output_dir = config["output_dir"]
        os.makedirs(output_dir, exist_ok=True)

        # Upload video to Supabase for public URL
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        uid = uuid.uuid4().hex[:8]
        video_url = upload_to_supabase(
            VIDEO_BUCKET, video_path, f"{ts}-{uid}-sora-character.mp4"
        )

        arguments: dict = {
            "video_url": video_url,
            "name": name,
        }

        self.log_prompt(config, arguments, model=SORA_CHARACTER_MODEL)

        request = fal_client.submit(SORA_CHARACTER_MODEL, arguments=arguments)
        request_id = request.request_id

        self._jobs[request_id] = {
            "output_dir": output_dir,
            "output_filename": config.get("output_filename", "character.json"),
            "name": name,
            "start_time": time.time(),
        }

        print(f"  [fal_sora_v2_character] Submitted request: {request_id}", file=sys.stderr)
        return request_id

    def poll(self, job_id: str) -> tuple[Status, dict]:
        job_info = self._jobs.get(job_id, {})
        elapsed = time.time() - job_info.get("start_time", time.time())
        metadata: dict = {"elapsed_seconds": round(elapsed, 1)}

        try:
            status = fal_client.status(SORA_CHARACTER_MODEL, job_id, with_logs=True)
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
                result = fal_client.result(SORA_CHARACTER_MODEL, job_id)
                character_id = result.get("character_id") or result.get("id")
                if not character_id:
                    metadata["error"] = f"No character_id in result: {result}"
                    return Status.FAILED, metadata

                output_dir = job_info.get("output_dir", ".")
                filename = job_info.get("output_filename", "character.json")
                output_path = os.path.join(output_dir, filename)

                # Save character ID to JSON for downstream nodes
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
                metadata["error"] = f"Failed to process result: {exc}"
                return Status.FAILED, metadata

        else:
            metadata["error"] = f"Unexpected FAL status type: {type(status).__name__}"
            return Status.FAILED, metadata

    def get_result(self, job_id: str) -> str:
        job_info = self._jobs.get(job_id, {})
        output_dir = job_info.get("output_dir", ".")
        filename = job_info.get("output_filename", "character.json")
        output_path = os.path.join(output_dir, filename)
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"Result not found: {output_path}")
        return output_path
