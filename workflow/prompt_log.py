"""Prompt logging for workflow runs.

Each adapter can call `save()` to dump the exact payload sent to its API
into `<run_dir>/prompts/<step_id>.json`. This gives full visibility into
what prompts each model actually received.

Binary data (base64 images, raw bytes) is replaced with a placeholder
to keep files readable.
"""

import json
import os
import re
from datetime import datetime, timezone


def _sanitize_value(value, max_str_len=200):
    """Replace binary/base64 data with readable placeholders."""
    if isinstance(value, bytes):
        return f"<binary {len(value)} bytes>"
    if isinstance(value, str):
        # Detect base64 data URIs
        if value.startswith("data:"):
            # Keep the mime type, truncate the data
            match = re.match(r"(data:[^;]+;base64,)", value)
            if match:
                data_len = len(value) - len(match.group(1))
                return f"{match.group(1)}<{data_len} chars>"
        # Detect raw base64 strings (long strings of base64 chars)
        if len(value) > 500 and re.match(r'^[A-Za-z0-9+/=\s]+$', value[:200]):
            return f"<base64 ~{len(value)} chars>"
        return value
    if isinstance(value, dict):
        return {k: _sanitize_value(v, max_str_len) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item, max_str_len) for item in value]
    return value


def save(prompt_log_dir: str, step_id: str, adapter_name: str, payload: dict,
         model: str = "", notes: str = "") -> str:
    """Save a prompt log entry for a step.

    Args:
        prompt_log_dir: Directory to write prompt files (typically <run_dir>/prompts/).
        step_id: The DAG step ID (e.g. "video_gen.shot_1").
        adapter_name: The adapter that sent this payload (e.g. "fal_kling_v3").
        payload: The exact dict/params sent to the API.
        model: Optional model identifier (e.g. "fal-ai/kling-video/v3/pro/image-to-video").
        notes: Optional notes about prompt construction.

    Returns:
        Path to the saved prompt file.
    """
    os.makedirs(prompt_log_dir, exist_ok=True)

    # Sanitize binary data for readability
    clean_payload = _sanitize_value(payload)

    entry = {
        "step_id": step_id,
        "adapter": adapter_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if model:
        entry["model"] = model
    entry["payload"] = clean_payload
    if notes:
        entry["notes"] = notes

    # Use step_id as filename, replacing dots with underscores
    filename = step_id.replace(".", "_") + ".json"
    filepath = os.path.join(prompt_log_dir, filename)

    with open(filepath, "w") as f:
        json.dump(entry, f, indent=2, default=str)

    return filepath
