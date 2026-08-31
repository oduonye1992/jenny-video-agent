"""ElevenLabs TTS narration adapter (sync)."""

import os
import sys

import requests
from dotenv import load_dotenv

from workflow.adapters.base import Adapter, Status
from workflow.adapters.registry import register

load_dotenv()

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"
DEFAULT_MODEL_ID = "eleven_v3"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_GUIDANCE_SCALE = 35
DEFAULT_LOUDNESS = 0.5

MAX_RETRIES = 3
RETRY_DELAY = 5





def _api_headers(api_key: str) -> dict:
    return {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }


def _http_post(url: str, headers: dict, json: dict = None, params: dict = None,
               timeout: int = 120) -> requests.Response:
    """POST with retries on transient failures."""
    import time
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(url, headers=headers, json=json, params=params, timeout=timeout)
            return resp
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


def _design_voice(
    voice_design_prompt: str,
    preview_text: str,
    guidance_scale: float,
    loudness: float,
    api_key: str,
    voice_name: str = "default-voice",
) -> str:
    """Design a new voice via ElevenLabs Voice Design API, save to library, return voice_id."""
    headers = _api_headers(api_key)

    payload: dict = {
        "voice_description": voice_design_prompt,
        "guidance_scale": guidance_scale,
        "loudness": loudness,
        "model_id": "eleven_ttv_v3",
    }

    if preview_text:
        payload["text"] = preview_text
    else:
        payload["auto_generate_text"] = True

    resp = _http_post(
        f"{ELEVENLABS_BASE}/text-to-voice/design",
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
    print(f"  [elevenlabs_tts] Voice designed: {generated_voice_id}", file=sys.stderr)

    # Save to library for a permanent voice_id
    save_resp = _http_post(
        f"{ELEVENLABS_BASE}/text-to-voice",
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

    print(f"  [elevenlabs_tts] Permanent voice_id: {voice_id}", file=sys.stderr)
    return voice_id


def _text_to_speech(
    script: str,
    voice_id: str,
    model_id: str,
    output_format: str,
    api_key: str,
) -> bytes:
    """Call ElevenLabs TTS API. Returns raw audio bytes."""
    resp = _http_post(
        f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}",
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
        },
        params={"output_format": output_format},
        json={
            "text": script,
            "model_id": model_id,
        },
        timeout=120,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"TTS failed ({resp.status_code}): {resp.text[:500]}")

    return resp.content


@register("elevenlabs_tts")
class ElevenLabsTTSAdapter(Adapter):
    """Wraps ElevenLabs TTS for narration generation.

    This is a SYNC adapter -- submit() blocks until audio is generated.

    Config keys:
        script (str): Full narration text (required).
        voice_id (str): Optional existing voice ID. If not provided, voice is designed.
        voice_design_prompt (str): Optional raw voice design prompt.
        language (str): Optional structured voice field.
        gender_age (str): Optional structured voice field.
        quality (str): Optional structured voice field.
        persona (str): Optional structured voice field.
        emotion (str): Optional structured voice field.
        delivery (str): Optional structured voice field.
        model_id (str): TTS model (default "eleven_v3").
        output_format (str): Audio format (default "mp3_44100_128").
        output_path (str): Where to save the audio file (required).
    """

    _results: dict[str, str] = {}

    @property
    def timeout_seconds(self) -> int:
        return 180

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

        script = config.get("script", "")
        if not script:
            raise ValueError("'script' is required")

        output_path = config["output_path"]
        voice_id = config.get("voice_id", "")
        model_id = config.get("model_id", DEFAULT_MODEL_ID)
        output_format = config.get("output_format", DEFAULT_OUTPUT_FORMAT)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        # Step 1: Voice design if needed
        if not voice_id:
            voice_design_prompt = _build_voice_prompt(config)
            if not voice_design_prompt:
                raise ValueError(
                    "Either 'voice_id' or voice design fields "
                    "(voice_design_prompt, persona, emotion, etc.) are required"
                )
            preview_text = config.get("preview_text", "")
            guidance_scale = float(config.get("guidance_scale", DEFAULT_GUIDANCE_SCALE))
            loudness = float(config.get("loudness", DEFAULT_LOUDNESS))

            voice_id = _design_voice(
                voice_design_prompt=voice_design_prompt,
                preview_text=preview_text,
                guidance_scale=guidance_scale,
                loudness=loudness,
                api_key=api_key,
            )

        # Log prompt before generating
        log_payload = {
            "script": script,
            "voice_id": voice_id,
            "model_id": model_id,
            "output_format": output_format,
        }
        if not config.get("voice_id"):
            log_payload["voice_design_prompt"] = voice_design_prompt
        self.log_prompt(config, log_payload, model=model_id)

        # Step 2: Generate narration
        print(
            f"  [elevenlabs_tts] Generating narration ({len(script)} chars, "
            f"voice: {voice_id[:12]}...)",
            file=sys.stderr,
        )

        audio_bytes = _text_to_speech(
            script=script,
            voice_id=voice_id,
            model_id=model_id,
            output_format=output_format,
            api_key=api_key,
        )

        with open(output_path, "wb") as f:
            f.write(audio_bytes)

        size_kb = round(len(audio_bytes) / 1024, 1)
        print(f"  [elevenlabs_tts] Saved: {output_path} ({size_kb} KB)", file=sys.stderr)

        self._results[output_path] = output_path
        return output_path

    def poll(self, job_id: str) -> tuple[Status, dict]:
        if os.path.exists(job_id):
            return Status.COMPLETED, {"progress": 1.0, "output": job_id}
        return Status.FAILED, {"error": f"Output file not found: {job_id}"}

    def get_result(self, job_id: str) -> str:
        if not os.path.exists(job_id):
            raise FileNotFoundError(f"Result not found: {job_id}")
        return job_id
