"""ElevenLabs Voice Design adapter (sync).

Designs a new voice from a text description using the ElevenLabs Voice Design API,
saves it to the voice library, and returns the permanent voice_id.

Use as a standalone DAG node before TTS to decouple voice creation from narration.
"""

import os
import sys

import requests
from dotenv import load_dotenv

from workflow.adapters.base import Adapter, Status
from workflow.adapters.registry import register

load_dotenv()

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"
DEFAULT_GUIDANCE_SCALE = 35
DEFAULT_LOUDNESS = 0.5

MAX_RETRIES = 3
RETRY_DELAY = 5





def _api_headers(api_key: str) -> dict:
    return {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }


def _http_post(url: str, headers: dict, json: dict = None, timeout: int = 120) -> requests.Response:
    """POST with retries on transient failures."""
    import time
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return requests.post(url, headers=headers, json=json, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as e:
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
    raise RuntimeError(f"HTTP POST failed after {MAX_RETRIES} attempts: {last_err}")


def _build_voice_prompt(config: dict) -> str:
    """Build an ElevenLabs-spec voice description from structured fields or raw prompt."""
    has_structured = any(
        config.get(k) for k in ("language", "gender_age", "quality", "persona", "emotion", "delivery")
    )

    if has_structured:
        parts = []
        for field in ("language", "gender_age", "quality"):
            if config.get(field):
                parts.append(config[field])
        line1 = ". ".join(parts) + "." if parts else ""

        persona = config.get("persona", "")
        emotion = config.get("emotion", "")
        line2_parts = []
        if persona:
            line2_parts.append(f"Persona: {persona}")
        if emotion:
            line2_parts.append(f"Emotion: {emotion}")
        line2 = ". ".join(line2_parts) + "." if line2_parts else ""

        delivery = config.get("delivery", "")
        return "\n".join(p for p in [line1, line2, delivery] if p).strip()

    return config.get("voice_design_prompt", "").strip()


@register("elevenlabs_voice_design")
class ElevenLabsVoiceDesignAdapter(Adapter):
    """Designs a voice via ElevenLabs and saves it to the library.

    This is a SYNC adapter -- submit() blocks until the voice is created.

    Config keys:
        voice_design_prompt (str): Raw voice description. Used if no structured fields.
        language (str): Optional structured field.
        gender_age (str): Optional structured field.
        quality (str): Optional structured field.
        persona (str): Optional structured field.
        emotion (str): Optional structured field.
        delivery (str): Optional structured field.
        preview_text (str): Optional text for the voice preview.
        voice_name (str): Name to save in library (default "default-voice").
        guidance_scale (float): Prompt adherence 0-100 (default 35).
        loudness (float): Output loudness 0-1 (default 0.5).
        output_dir (str): Directory to save the preview audio (optional).
    """

    _results: dict[str, dict] = {}

    @property
    def timeout_seconds(self) -> int:
        return 120

    @property
    def is_sync(self) -> bool:
        return True

    @property
    def input_types(self) -> dict[str, str]:
        return {}

    @property
    def output_type(self) -> str:
        return "audio"

    def submit(self, config: dict) -> str:
        api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        if not api_key:
            raise RuntimeError("ELEVENLABS_API_KEY not set in environment")

        voice_design_prompt = _build_voice_prompt(config)
        if not voice_design_prompt:
            raise RuntimeError(
                "Voice design requires a voice description. Provide 'voice_design_prompt' "
                "or structured fields ('language', 'gender_age', 'persona', 'emotion', 'delivery'). "
                "Every concept must define its own voice — there are no defaults."
            )

        voice_name = config.get("voice_name", "default-voice")
        preview_text = config.get("preview_text", "")
        guidance_scale = float(config.get("guidance_scale", DEFAULT_GUIDANCE_SCALE))
        loudness = float(config.get("loudness", DEFAULT_LOUDNESS))
        output_dir = config.get("output_dir")

        headers = _api_headers(api_key)

        # Step 1: Create voice previews
        payload: dict = {
            "voice_description": voice_design_prompt,
            "guidance_scale": guidance_scale,
            "loudness": loudness,
        }

        if preview_text:
            payload["text"] = preview_text
        else:
            payload["auto_generate_text"] = True

        self.log_prompt(config, payload, model="elevenlabs_voice_design",
                        notes=f"voice_name={voice_name}")

        print(f"  [voice_design] Designing voice: {voice_name}", file=sys.stderr)
        resp = _http_post(
            f"{ELEVENLABS_BASE}/text-to-voice/create-previews",
            headers=headers,
            json=payload,
            timeout=120,
        )

        if resp.status_code != 200:
            raise RuntimeError(f"Voice design failed ({resp.status_code}): {resp.text[:500]}")

        data = resp.json()
        previews = data.get("previews", [])
        if not previews:
            raise RuntimeError("Voice design returned no previews.")

        generated_voice_id = previews[0]["generated_voice_id"]
        print(f"  [voice_design] Preview generated: {generated_voice_id}", file=sys.stderr)

        # Save preview audio if output_dir specified
        if output_dir:
            import base64
            os.makedirs(output_dir, exist_ok=True)
            for i, preview in enumerate(previews):
                audio_b64 = preview.get("audio_base_64", "")
                if audio_b64:
                    path = os.path.join(output_dir, f"voice_preview_{i+1}.mp3")
                    with open(path, "wb") as f:
                        f.write(base64.b64decode(audio_b64))
                    print(f"  [voice_design] Preview saved: {path}", file=sys.stderr)

        # Step 2: Save to library for a permanent voice_id
        save_resp = _http_post(
            f"{ELEVENLABS_BASE}/text-to-voice/create-voice-from-preview",
            headers=headers,
            json={
                "voice_name": voice_name,
                "voice_description": voice_design_prompt[:500],
                "generated_voice_id": generated_voice_id,
            },
            timeout=60,
        )

        if save_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to save voice to library ({save_resp.status_code}): {save_resp.text[:500]}"
            )

        voice_id = save_resp.json().get("voice_id", "")
        if not voice_id:
            raise RuntimeError(f"No voice_id in save response: {save_resp.json()}")

        print(f"  [voice_design] Permanent voice_id: {voice_id}", file=sys.stderr)

        self._results[voice_id] = {
            "voice_id": voice_id,
            "voice_name": voice_name,
            "voice_design_prompt": voice_design_prompt,
            "preview_count": len(previews),
        }
        return voice_id

    def poll(self, job_id: str) -> tuple[Status, dict]:
        if job_id in self._results:
            return Status.COMPLETED, {"progress": 1.0, "voice_id": job_id}
        return Status.FAILED, {"error": f"Voice not found: {job_id}"}

    def get_result(self, job_id: str) -> str:
        if job_id not in self._results:
            raise KeyError(f"Voice result not found: {job_id}")
        return job_id
