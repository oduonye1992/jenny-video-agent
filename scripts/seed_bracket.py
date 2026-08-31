"""Seed bracketing — test the same prompt across a range of seeds in parallel.

Usage:
    python scripts/seed_bracket.py \\
        --adapter fal_veo_v3_flf \\
        --config '{"start_frame_path": "frame.png", "prompt": "...", "output_dir": "outputs/brackets/test1"}' \\
        --start-seed 1000 \\
        --count 11

This submits `count` jobs (seeds 1000-1010) in parallel, polls them all,
and saves results as <output_dir>/seed_<N>.<ext> with a summary JSON.

Supported adapters: any adapter that accepts a "seed" config key
(fal_veo_v3_flf, fal_seedance_v1_5, fal_nano_banana_v2).
"""

import argparse
import json
import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflow.adapters.registry import get_adapter
from workflow.adapters.base import Status


SEED_ADAPTERS = {
    "fal_veo_v3_flf",
    "fal_seedance_v1_5",
    "fal_nano_banana_v2",
}


def run_bracket(adapter_name: str, base_config: dict, start_seed: int, count: int):
    if adapter_name not in SEED_ADAPTERS:
        print(f"Warning: {adapter_name} not in known seed-supporting adapters: {SEED_ADAPTERS}", file=sys.stderr)

    output_dir = base_config.get("output_dir", "outputs/brackets")
    os.makedirs(output_dir, exist_ok=True)

    seeds = list(range(start_seed, start_seed + count))
    jobs: list[dict] = []

    # Submit all jobs in parallel
    print(f"Submitting {count} jobs with seeds {seeds[0]}-{seeds[-1]}...", file=sys.stderr)

    for seed in seeds:
        adapter = get_adapter(adapter_name)
        config = {**base_config}
        config["seed"] = seed

        # Name output files by seed
        ext = "png" if "nano_banana" in adapter_name or "dreamina" in adapter_name else "mp4"
        config["output_filename"] = f"seed_{seed}.{ext}"

        try:
            job_id = adapter.submit(config)
            jobs.append({
                "seed": seed,
                "job_id": job_id,
                "adapter": adapter,
                "status": "submitted",
                "metadata": {},
            })
            print(f"  seed {seed}: submitted ({job_id})", file=sys.stderr)
        except Exception as exc:
            jobs.append({
                "seed": seed,
                "job_id": None,
                "adapter": adapter,
                "status": "failed",
                "metadata": {"error": str(exc)},
            })
            print(f"  seed {seed}: FAILED to submit — {exc}", file=sys.stderr)

    # Poll all jobs until done
    print(f"\nPolling {len([j for j in jobs if j['job_id']])} active jobs...", file=sys.stderr)
    poll_interval = 10
    max_time = 900  # 15 min total timeout

    start_time = time.time()
    while True:
        all_done = True
        for job in jobs:
            if job["status"] in ("completed", "failed") or job["job_id"] is None:
                continue
            all_done = False
            status, metadata = job["adapter"].poll(job["job_id"])
            job["metadata"] = metadata
            if status == Status.COMPLETED:
                job["status"] = "completed"
                output_path = metadata.get("output", "")
                print(f"  seed {job['seed']}: COMPLETED → {output_path}", file=sys.stderr)
            elif status == Status.FAILED:
                job["status"] = "failed"
                print(f"  seed {job['seed']}: FAILED — {metadata.get('error', 'unknown')}", file=sys.stderr)

        if all_done:
            break

        elapsed = time.time() - start_time
        if elapsed > max_time:
            print(f"\nTimeout after {max_time}s. Marking remaining jobs as failed.", file=sys.stderr)
            for job in jobs:
                if job["status"] not in ("completed", "failed"):
                    job["status"] = "failed"
                    job["metadata"]["error"] = "timeout"
            break

        active = len([j for j in jobs if j["status"] not in ("completed", "failed") and j["job_id"]])
        print(f"  ... {active} jobs still running ({round(elapsed)}s elapsed)", file=sys.stderr)
        time.sleep(poll_interval)

    # Build summary
    summary = {
        "adapter": adapter_name,
        "seed_range": f"{seeds[0]}-{seeds[-1]}",
        "prompt": base_config.get("prompt", ""),
        "results": [],
    }

    completed = 0
    for job in jobs:
        entry = {
            "seed": job["seed"],
            "status": job["status"],
        }
        if job["status"] == "completed":
            output = job["metadata"].get("output", "")
            entry["output"] = output
            entry["result_url"] = job["metadata"].get("result_url", "")
            completed += 1
        else:
            entry["error"] = job["metadata"].get("error", "unknown")
        summary["results"].append(entry)

    summary["completed"] = completed
    summary["failed"] = count - completed

    # Save summary
    summary_path = os.path.join(output_dir, "bracket_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nDone: {completed}/{count} succeeded", file=sys.stderr)
    print(f"Summary: {summary_path}", file=sys.stderr)
    print(f"Outputs: {output_dir}/", file=sys.stderr)

    # Print summary to stdout for Claude to consume
    print(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description="Seed bracketing for video/image generation")
    parser.add_argument("--adapter", required=True, help="Adapter name (e.g. fal_veo_v3_flf)")
    parser.add_argument("--config", required=True, help="Base config as JSON string")
    parser.add_argument("--start-seed", type=int, default=1000, help="First seed (default 1000)")
    parser.add_argument("--count", type=int, default=11, help="Number of seeds to test (default 11)")
    args = parser.parse_args()

    base_config = json.loads(args.config)
    run_bracket(args.adapter, base_config, args.start_seed, args.count)


if __name__ == "__main__":
    main()
