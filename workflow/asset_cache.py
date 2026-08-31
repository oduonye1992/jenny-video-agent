"""Asset cache: skip re-generation when the same inputs have been seen before.

Docker-style recursive cache keys: each step's key includes its adapter name,
config, and the cache keys of all its dependencies. A change to any upstream
step invalidates all downstream steps automatically.

Cache file: outputs/.asset_cache.json
Thread-safe via atomic write (write to temp file, then os.replace).
"""

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone

CACHE_PATH = "outputs/.asset_cache.json"

# Config keys to EXCLUDE from the hash — they vary per run but don't affect the output content.
_EXCLUDED_KEYS = {"output_dir", "output_filename", "output_path"}

# Adapter categories that should NOT be cached (fast, deterministic, local).
UNCACHEABLE_ADAPTERS = {
    "local_ffmpeg", "pil_render",
    "ffmpeg_concat", "ffmpeg_mix_audio",
    "ffmpeg_extract_last_frame", "ffmpeg_extract_first_frame",
}


def _load_cache() -> dict:
    """Load the cache file, returning an empty dict if missing or corrupt."""
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache_file(cache: dict) -> None:
    """Atomically write the cache dict to disk."""
    os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(CACHE_PATH) or ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(cache, f, indent=2, sort_keys=True)
        os.replace(tmp_path, CACHE_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _filter_config(config: dict) -> dict:
    """Return config with excluded and internal keys removed."""
    return {
        k: v for k, v in config.items()
        if k not in _EXCLUDED_KEYS and not k.startswith("_")
    }


def cache_key(adapter_name: str, config: dict) -> str:
    """Generate a deterministic SHA-256 hash from adapter name + relevant config keys.

    This is the flat (non-recursive) key — used only as a building block for
    recursive_cache_key. Do not use directly for cache lookups.
    """
    filtered = _filter_config(config)
    payload = json.dumps(
        {"adapter": adapter_name, "config": filtered},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def recursive_cache_key(step_id: str, dag: "DAG") -> str:
    """Compute Docker-style cache key: own config + dependency cache keys.

    The cache key for a step includes its adapter name, filtered config,
    and the cache keys of all its dependencies (sorted). This means any
    change to a step's config or any upstream step's config invalidates
    the cache for this step and all downstream steps.
    """
    from workflow.dag import DAG  # noqa: F811 - local import to avoid circular
    step = dag.get_step(step_id)
    dep_keys = sorted(recursive_cache_key(dep, dag) for dep in step.depends_on)
    filtered = _filter_config(step.config)
    payload = json.dumps({
        "adapter": step.adapter_name,
        "config": filtered,
        "dep_keys": dep_keys,
    }, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def check_cache(step) -> str | None:
    """Return the cached output path if the step's recursive cache key has a hit.

    Uses the pre-computed recursive cache key on the step (includes upstream deps).
    Returns None for uncacheable adapters or if the cached file no longer exists.
    """
    if step.adapter_name in UNCACHEABLE_ADAPTERS:
        return None

    if not step.cache_key:
        return None

    cache = _load_cache()
    entry = cache.get(step.cache_key)
    if not isinstance(entry, dict):
        return None

    output_path = entry.get("output")
    if output_path and os.path.exists(output_path):
        return output_path

    return None


def save_cache(step, output_path: str) -> None:
    """Save the mapping from recursive cache key to output path with metadata.

    Each entry stores the output path, adapter name, step ID, and timestamp
    for debuggability. Does not apply to uncacheable adapters.
    Thread-safe via atomic write.
    """
    if step.adapter_name in UNCACHEABLE_ADAPTERS:
        return

    if not step.cache_key:
        return

    cache = _load_cache()
    cache[step.cache_key] = {
        "output": output_path,
        "adapter": step.adapter_name,
        "step_id": step.step_id,
        "created": datetime.now(timezone.utc).isoformat(),
    }
    _save_cache_file(cache)
