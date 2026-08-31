"""ElevenLabs music generation adapter (sync)."""

import os
import re
import sys

import requests
from dotenv import load_dotenv

from workflow.adapters.base import Adapter, Status
from workflow.adapters.registry import register

load_dotenv()

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"
DEFAULT_MODEL_ID = "music_v1"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_MUSIC_LENGTH_MS = 10000

MAX_RETRIES = 3
RETRY_DELAY = 5


def _http_post(url: str, headers: dict, json: dict = None, params: dict = None,
               timeout: int = 300) -> requests.Response:
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


def _to_snake(name: str) -> str:
    """Convert camelCase to snake_case."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _normalise_section(section: dict) -> dict:
    """Normalise a single section dict from camelCase to snake_case."""
    out: dict = {}
    for k, v in section.items():
        out[_to_snake(k)] = v
    return out


def _build_composition_plan(config: dict) -> dict | None:
    """Build the ElevenLabs composition_plan from config. Returns None for prompt mode."""
    pos_global = config.get("positiveGlobalStyles") or config.get("positive_global_styles")
    neg_global = config.get("negativeGlobalStyles") or config.get("negative_global_styles")
    sections_raw = config.get("sections", [])

    if not pos_global and not sections_raw:
        return None

    plan: dict = {}
    if pos_global:
        plan["positive_global_styles"] = pos_global
    if neg_global:
        plan["negative_global_styles"] = neg_global
    if sections_raw:
        plan["sections"] = [_normalise_section(s) for s in sections_raw]

    return plan


def _total_duration_ms(composition_plan: dict | None, config: dict) -> int:
    """Compute total music duration in ms.

    ElevenLabs music tends to fade/go silent near the end of the requested
    duration. To ensure full coverage, we add a 10-second buffer to the
    requested length. The calling workflow should use FFmpeg's -shortest
    flag to trim the excess when mixing into the final video.
    """
    OVERSHOOT_MS = 10_000  # 10 seconds extra to avoid empty tail

    explicit = config.get("music_length_ms")
    if explicit:
        return int(explicit) + OVERSHOOT_MS
    if composition_plan:
        sections = composition_plan.get("sections", [])
        if sections:
            return sum(s.get("duration_ms", 0) for s in sections) + OVERSHOOT_MS
    return DEFAULT_MUSIC_LENGTH_MS + OVERSHOOT_MS


@register("elevenlabs_music")
class ElevenLabsMusicAdapter(Adapter):
    """Wraps ElevenLabs music generation API.

    This is a SYNC adapter -- submit() blocks until music is generated.

    Config keys:
        prompt (str): Optional simple text prompt for music generation.
        positiveGlobalStyles (list[str]): Optional composition plan styles.
        negativeGlobalStyles (list[str]): Optional negative styles.
        sections (list[dict]): Optional section definitions with durations.
        music_length_ms (int): Total duration in ms (default sum of sections or 10000).
        output_path (str): Where to save the audio file (required).
    """

    _results: dict[str, str] = {}

    @property
    def timeout_seconds(self) -> int:
        return 300

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

        output_path = config["output_path"]
        prompt = config.get("prompt", "")
        model_id = config.get("model_id", DEFAULT_MODEL_ID)
        output_format = config.get("output_format", DEFAULT_OUTPUT_FORMAT)

        composition_plan = _build_composition_plan(config)
        music_length_ms = _total_duration_ms(composition_plan, config)

        if not prompt and composition_plan is None:
            raise ValueError(
                "Provide either 'prompt' or a composition plan "
                "(positiveGlobalStyles + sections)"
            )

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        # Build API payload
        payload: dict = {
            "model_id": model_id,
            "output_format": output_format,
        }

        if composition_plan:
            payload["composition_plan"] = composition_plan
            mode = "composition_plan"
            # ElevenLabs rejects music_length_ms when composition_plan is provided
        else:
            payload["prompt"] = prompt
            payload["music_length_ms"] = music_length_ms
            mode = "prompt"

        # Log prompt before generating
        self.log_prompt(config, payload, model=model_id,
                        notes=f"mode={mode}, requested_duration={music_length_ms}ms (includes +10s overshoot)")

        print(
            f"  [elevenlabs_music] Generating music (mode={mode}, {music_length_ms}ms)...",
            file=sys.stderr,
        )

        resp = _http_post(
            f"{ELEVENLABS_BASE}/music",
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
            },
            params={"output_format": output_format},
            json=payload,
            timeout=300,
        )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Music generation failed ({resp.status_code}): {resp.text[:500]}"
            )

        audio_bytes = resp.content

        with open(output_path, "wb") as f:
            f.write(audio_bytes)

        size_kb = round(len(audio_bytes) / 1024, 1)
        print(f"  [elevenlabs_music] Saved: {output_path} ({size_kb} KB)", file=sys.stderr)

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
