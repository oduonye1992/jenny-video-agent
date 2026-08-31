"""Spend tracking for production runs.

Appends actual cost entries to a project-wide spend log (outputs/spend_log.json)
after each step completes. Provides total spend queries with optional date filtering.
"""

import json
import os
from datetime import datetime, timezone

from workflow.cost import COST_PER_STEP

# Project-wide spend log path
SPEND_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "outputs",
    "spend_log.json",
)


def log_spend(
    adapter_name: str,
    step_id: str,
    run_name: str,
    output_dir: str | None = None,
) -> dict:
    """Append a spend entry to the project-wide spend log.

    Uses COST_PER_STEP for the cost lookup. Returns the entry that was logged.
    """
    cost = COST_PER_STEP.get(adapter_name, 0.0)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_name": run_name,
        "step_id": step_id,
        "adapter": adapter_name,
        "cost_usd": cost,
    }

    log_path = SPEND_LOG_PATH

    # Read existing entries
    entries = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                entries = json.load(f)
        except (json.JSONDecodeError, ValueError):
            entries = []

    entries.append(entry)

    # Write back
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w") as f:
        json.dump(entries, f, indent=2)

    return entry


def get_total_spend(since_date: str | None = None) -> float:
    """Read the spend log and return total spend in USD.

    Args:
        since_date: Optional ISO date string (e.g. "2026-03-01"). If provided,
                    only entries on or after this date are included.

    Returns:
        Total spend in USD as a float.
    """
    log_path = SPEND_LOG_PATH

    if not os.path.exists(log_path):
        return 0.0

    try:
        with open(log_path, "r") as f:
            entries = json.load(f)
    except (json.JSONDecodeError, ValueError):
        return 0.0

    if since_date:
        # Parse the filter date (accept date or datetime strings)
        if "T" not in since_date:
            since_date += "T00:00:00+00:00"
        since_dt = datetime.fromisoformat(since_date)
        total = 0.0
        for entry in entries:
            try:
                entry_dt = datetime.fromisoformat(entry["timestamp"])
                if entry_dt >= since_dt:
                    total += entry.get("cost_usd", 0.0)
            except (KeyError, ValueError):
                continue
        return round(total, 2)

    total = sum(entry.get("cost_usd", 0.0) for entry in entries)
    return round(total, 2)
