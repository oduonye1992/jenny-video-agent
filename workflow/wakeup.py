"""Wakeup mechanism for signaling completion back to Claude.

Option A (file-based, for Claude Code): writes __wakeup__.json
Option B (stdout, for Slack): prints a wakeup line
"""

import json
import os
from datetime import datetime, timezone


def write_wakeup(output_dir: str, run_name: str, status: str, output_path: str | None = None,
                 error: str | None = None) -> str:
    """Write __wakeup__.json to the output directory."""
    os.makedirs(output_dir, exist_ok=True)
    wakeup_path = os.path.join(output_dir, "__wakeup__.json")

    wakeup = {
        "job_id": run_name,
        "status": status,
        "output": output_path,
        "error": error,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(wakeup_path, "w") as f:
        json.dump(wakeup, f, indent=2)

    return wakeup_path


def print_wakeup(run_name: str, status: str, output_path: str | None = None):
    """Print a wakeup line to stdout (for Slack bot integration)."""
    parts = [f"__wakeup__ job_id={run_name} status={status}"]
    if output_path:
        parts.append(f"output={output_path}")
    print(" ".join(parts))


def check_wakeup(output_dir: str) -> dict | None:
    """Check if a wakeup file exists. Returns the wakeup dict or None."""
    wakeup_path = os.path.join(output_dir, "__wakeup__.json")
    if not os.path.exists(wakeup_path):
        return None
    with open(wakeup_path) as f:
        return json.load(f)
