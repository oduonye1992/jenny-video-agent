"""Status tracking for workflow engine runs.

Reads and writes status.json to the output directory.
"""

import json
import os
from datetime import datetime, timezone

from workflow.dag import DAG


def write_status(dag: DAG, output_dir: str, run_name: str, started: str | None = None,
                 fallbacks_used: list | None = None, errors: list | None = None,
                 cost: dict | None = None) -> str:
    """Write status.json to the output directory. Returns the path."""
    os.makedirs(output_dir, exist_ok=True)
    status_path = os.path.join(output_dir, "status.json")

    now = datetime.now(timezone.utc)
    started_str = started or now.isoformat()

    steps_dict = {}
    for step_id, step in dag.steps.items():
        entry: dict = {
            "status": step.status.value,
            "adapter": step.adapter_name,
        }
        if step.duration_s > 0:
            entry["duration_s"] = round(step.duration_s, 1)
        if step.output:
            entry["output"] = step.output
        if step.error:
            entry["error"] = step.error
        if step.retries > 0:
            entry["retries"] = step.retries
        if step.cache_key:
            entry["cache_key"] = step.cache_key
        if step.cache_hit:
            entry["cache_hit"] = True
        steps_dict[step_id] = entry

    # Compute total wall time
    total_duration_s = round(sum(
        step.duration_s for step in dag.steps.values() if step.duration_s > 0
    ), 1)

    # Compute wall clock elapsed
    try:
        start_dt = datetime.fromisoformat(started_str)
        elapsed_s = round((now - start_dt).total_seconds(), 1)
    except (ValueError, TypeError):
        elapsed_s = total_duration_s

    status = {
        "job_id": run_name,
        "started": started_str,
        "updated": now.isoformat(),
        "complete": dag.is_complete(),
        "failed": dag.has_failed(),
        "elapsed_s": elapsed_s,
        "total_step_duration_s": total_duration_s,
        "steps": steps_dict,
        "fallbacks_used": fallbacks_used or [],
        "errors": errors or [],
    }

    if cost:
        status["cost"] = cost

    # Add completed_at timestamp when the run finishes
    if dag.is_complete() or dag.has_failed():
        status["completed_at"] = now.isoformat()

    with open(status_path, "w") as f:
        json.dump(status, f, indent=2)

    return status_path


def read_status(output_dir: str) -> dict:
    """Read status.json from the output directory."""
    status_path = os.path.join(output_dir, "status.json")
    with open(status_path) as f:
        return json.load(f)
