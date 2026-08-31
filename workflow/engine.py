"""Workflow engine: reads a production spec, builds a DAG, and executes it.

Usage:
    python workflow/engine.py --spec production_spec.json
    python workflow/engine.py --spec production_spec.json --background
    python workflow/engine.py --spec production_spec.json --validate
    python workflow/engine.py --spec production_spec.json --dump-prompts
    python workflow/engine.py --status outputs/runs/<run_name>/status.json

Dump prompts for review (no generation, no cost):
    python workflow/engine.py --spec production_spec.json --dump-prompts

Resume a failed run (re-runs only failed/pending steps):
    python workflow/engine.py --spec production_spec.json --retry outputs/runs/<run_name>/status.json
    python workflow/engine.py --spec production_spec.json --retry outputs/runs/<run_name>/status.json --step video_gen.shot_2
    python workflow/engine.py --spec production_spec.json --retry outputs/runs/<run_name>/status.json --step video_gen.shot_2 --adapter fal_kling_v3

Approve quality gate and continue:
    python workflow/engine.py --spec production_spec.json --retry outputs/runs/<run_name>/status.json --approve-gate
"""

import os
import sys

# Ensure project root is on sys.path so `workflow` package is importable
# when running as `python workflow/engine.py` from the project directory.
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import argparse
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from workflow.adapters.base import Status
from workflow.adapters.registry import get_adapter
from workflow.cost import estimate_cost, COST_PER_STEP
from workflow.spend_log import log_spend
from workflow.dag import DAG, Step
from workflow.asset_cache import check_cache, save_cache
from workflow.model_profiles import resolve_all
from workflow.spec_validator import validate_spec
from workflow.status import write_status, read_status
from workflow.wakeup import write_wakeup, print_wakeup
from workflow.compiler import compile_spec, load_spec, format_dag_graph


logger = logging.getLogger("workflow.engine")


def _fmt_list(items: list, indent: str = "  ") -> str:
    """Format a list as readable bullet points."""
    return "\n".join(f"{indent}- {item}" for item in items)


def _fmt_nano_banana_spec(spec: dict) -> str:
    """Format a Nano Banana JSON spec as JSON — exactly what the API receives."""
    return json.dumps(spec, indent=2)


def _fmt_music_composition(config: dict) -> str:
    """Format a music composition plan as readable plain text."""
    lines = []
    pos = config.get("positiveGlobalStyles", [])
    neg = config.get("negativeGlobalStyles", [])
    if pos:
        lines.append(f"Global styles: {', '.join(pos)}")
    if neg:
        lines.append(f"Avoid: {', '.join(neg)}")
    lines.append("")

    sections = config.get("sections", [])
    for i, s in enumerate(sections, 1):
        name = s.get("sectionName", s.get("section_name", f"Section {i}"))
        duration_ms = s.get("durationMs", s.get("duration_ms", 0))
        duration_s = duration_ms / 1000
        local_pos = s.get("positiveLocalStyles", s.get("positive_local_styles", []))
        local_neg = s.get("negativeLocalStyles", s.get("negative_local_styles", []))
        lines.append(f"[{name}] ({duration_s:.0f}s)")
        if local_pos:
            lines.append(f"  Styles: {', '.join(local_pos)}")
        if local_neg:
            lines.append(f"  Avoid: {', '.join(local_neg)}")
        lines.append("")

    return "\n".join(lines)


def dump_prompts(dag: DAG, prompts_dir: str) -> None:
    """Dump all prompts from the DAG as plain text BEFORE execution.

    Writes one .txt file per step so every prompt can be reviewed before
    any money is spent. All files are human-readable plain text — no JSON.

    Only dumps steps that are PENDING (skips completed steps on resume).
    """
    os.makedirs(prompts_dir, exist_ok=True)

    for step_id, step in dag.steps.items():
        if step.status != Status.PENDING:
            continue

        config = step.config
        safe_name = step_id.replace(".", "_")
        txt_path = os.path.join(prompts_dir, f"{safe_name}.txt")

        # Image gen — dump Nano Banana spec as readable text
        if step_id.startswith("image_gen"):
            nano_spec = config.get("nano_banana_spec")
            prompt = config.get("prompt", "")
            with open(txt_path, "w") as f:
                f.write(f"Step: {step_id}\n")
                f.write(f"Adapter: {step.adapter_name}\n")
                f.write(f"Aspect ratio: {config.get('aspect_ratio', '9:16')}\n")
                f.write("─" * 60 + "\n\n")
                if nano_spec:
                    f.write(_fmt_nano_banana_spec(nano_spec))
                elif prompt:
                    f.write(prompt)

        # Video gen — dump the video_prompt as plain text
        elif step_id.startswith("video_gen"):
            prompt = config.get("prompt", "")
            with open(txt_path, "w") as f:
                f.write(f"Step: {step_id}\n")
                f.write(f"Adapter: {step.adapter_name}\n")
                f.write(f"Duration: {config.get('duration', '?')}s\n")
                f.write(f"Aspect ratio: {config.get('aspect_ratio', '9:16')}\n")
                f.write("─" * 60 + "\n\n")
                f.write(prompt)

        # TTS — dump the narration script
        elif step_id == "tts":
            script = config.get("script", "")
            hook = config.get("hook", "")
            voice_id = config.get("voice_id", "")
            voice_desc = config.get("voice_description", "")
            with open(txt_path, "w") as f:
                f.write(f"Step: {step_id}\n")
                f.write(f"Adapter: {step.adapter_name}\n")
                if voice_id:
                    f.write(f"Voice ID: {voice_id}\n")
                if voice_desc:
                    f.write(f"Voice: {voice_desc}\n")
                f.write("─" * 60 + "\n\n")
                f.write(f"HOOK\n{hook}\n\n")
                f.write(f"SCRIPT\n{script}\n")

        # Music — dump prompt + composition plan as readable text
        elif step_id == "music":
            prompt = config.get("prompt", "")
            sections = config.get("sections")
            with open(txt_path, "w") as f:
                f.write(f"Step: {step_id}\n")
                f.write(f"Adapter: {step.adapter_name}\n")
                f.write("─" * 60 + "\n\n")
                if prompt:
                    f.write(f"PROMPT\n{prompt}\n\n")
                if sections:
                    f.write("COMPOSITION PLAN\n")
                    f.write(_fmt_music_composition(config))

        # Merge — readable summary (supports both local_ffmpeg and ffmpeg_concat)
        elif step_id == "merge_videos":
            clip_paths = config.get("clip_paths", [])
            with open(txt_path, "w") as f:
                f.write(f"Step: {step_id}\n")
                f.write(f"Adapter: {step.adapter_name}\n")
                f.write(f"Resolution: {config.get('resolution', '720:1280')}\n")
                f.write("─" * 60 + "\n\n")
                f.write("CLIPS (in order)\n")
                for i, p in enumerate(clip_paths, 1):
                    f.write(f"  {i}. {p}\n")
                f.write(f"\nOutput: {config.get('output_path', '')}\n")

        # Mix audio — readable summary (supports both local_ffmpeg and ffmpeg_mix_audio)
        elif step_id == "mix_audio":
            with open(txt_path, "w") as f:
                f.write(f"Step: {step_id}\n")
                f.write(f"Adapter: {step.adapter_name}\n")
                f.write("─" * 60 + "\n\n")
                f.write(f"Video:     {config.get('video_path', '')}\n")
                f.write(f"Narration: {config.get('narration_path', '')}\n")
                f.write(f"Music:     {config.get('music_path', '')}\n")
                f.write(f"Music vol: {config.get('music_volume_db', -12)} dB\n")
                f.write(f"\nOutput: {config.get('output_path', '')}\n")

        # Upscale — readable summary
        elif step_id.startswith("upscale"):
            with open(txt_path, "w") as f:
                f.write(f"Step: {step_id}\n")
                f.write(f"Adapter: {step.adapter_name}\n")
                f.write("─" * 60 + "\n\n")
                f.write(f"Input:  {config.get('video_path', '')}\n")
                f.write(f"Output: {config.get('output_dir', '')}/{config.get('output_filename', '')}\n")
                f.write(f"Aspect: {config.get('aspect_ratio', '9:16')}\n")

    logger.debug("Dumped %d prompt files to %s/", len(os.listdir(prompts_dir)), prompts_dir)


def setup_logging(output_dir: str | None = None) -> None:
    """Configure logging to stderr and optionally to a log file in output_dir."""
    root = logging.getLogger("workflow")
    root.setLevel(logging.DEBUG)

    # Always log to stderr
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.INFO)
    stderr_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(stderr_handler)

    # Log to file if output_dir is provided
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        file_handler = logging.FileHandler(
            os.path.join(output_dir, "engine.log"),
            mode="a",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        ))
        root.addHandler(file_handler)


def build_dag(spec: dict) -> DAG:
    """Build a DAG from a production spec via the template registry.

    Convenience function — equivalent to DAG.from_json(compile_spec(spec)).
    """
    return DAG.from_json(compile_spec(spec))


def _next_run_dir(base_dir: str) -> str:
    """Return the next available runs/NNN/ subfolder inside base_dir.

    Scans for existing runs/001/, runs/002/, etc. and returns the next number.
    If no runs/ folder exists yet, returns runs/001/.
    """
    runs_dir = os.path.join(base_dir, "runs")
    if not os.path.isdir(runs_dir):
        return os.path.join(runs_dir, "001")

    existing = []
    for name in os.listdir(runs_dir):
        if name.isdigit() and os.path.isdir(os.path.join(runs_dir, name)):
            existing.append(int(name))

    next_num = max(existing) + 1 if existing else 1
    return os.path.join(runs_dir, f"{next_num:03d}")


def execute_pipeline(pipeline_path: str, output_dir: str | None = None,
                     dry_run: bool = False,
                     resume_from: str | None = None) -> bool:
    """Load and execute a pre-compiled pipeline JSON.

    Args:
        pipeline_path: Path to pipeline.json file.
        output_dir: Override output directory (default: from pipeline metadata).
        dry_run: If True, validate and print the graph without executing.
        resume_from: Path to status.json to resume from. When set, skips
            auto-versioning and restores completed steps from the status file.
            The output_dir must already exist and contain the status file.

    Returns True if execution completed successfully (or dry_run passed).
    """
    with open(pipeline_path) as f:
        pipeline = json.load(f)

    # Validate the pipeline
    from workflow.pipeline_validator import validate_pipeline
    errors = validate_pipeline(pipeline)
    if errors:
        logger.error("Pipeline validation failed with %d error(s):", len(errors))
        for err in errors:
            logger.error("  - %s", err)
        return False

    dag = DAG.from_json(pipeline)
    base_output_dir = output_dir or pipeline.get("output_dir", "outputs/runs/unnamed")
    run_name = pipeline.get("run_name", "pipeline")

    if dry_run:
        print(format_dag_graph(dag))
        print(f"\nPipeline valid: {len(dag.steps)} steps, 0 errors.")
        return True

    if resume_from:
        # Resume mode: use the provided output_dir directly (no auto-versioning)
        output_dir = base_output_dir
        os.makedirs(output_dir, exist_ok=True)

        # Restore completed steps from the status file
        with open(resume_from) as f:
            prev_status = json.load(f)
        for step_id, step in dag.steps.items():
            info = prev_status.get("steps", {}).get(step_id, {})
            if info.get("status") == "completed" and info.get("output"):
                step.status = Status.COMPLETED
                step.output = info["output"]
                step.duration_s = info.get("duration_s", 0)

        restored = sum(1 for s in dag.steps.values() if s.status == Status.COMPLETED)
        pending = len(dag.steps) - restored
        logger.info("Resumed: %d completed, %d to re-run", restored, pending)

        # Reset failed steps so status.json reflects the retry immediately
        for step_id, step in dag.steps.items():
            if step.status != Status.COMPLETED:
                step.status = Status.PENDING
                step.error = None

        # Write status immediately so the UI sees the run is in progress
        started = datetime.now(timezone.utc).isoformat()
        write_status(dag, output_dir, run_name, started)
    else:
        # Auto-version: if output_dir is a concept folder, create runs/NNN/ subfolder
        output_dir = _next_run_dir(base_output_dir)

        os.makedirs(output_dir, exist_ok=True)

        # Copy pipeline.json into the run folder for provenance
        import shutil
        shutil.copy2(pipeline_path, os.path.join(output_dir, "pipeline.json"))

    setup_logging(output_dir)

    # Compute cache keys for all nodes
    from workflow.asset_cache import recursive_cache_key
    for step_id in dag.steps:
        dag.steps[step_id].cache_key = recursive_cache_key(step_id, dag)

    started = datetime.now(timezone.utc).isoformat()

    logger.info(
        "Executing pipeline '%s' with %d steps from %s",
        run_name, len(dag.steps), pipeline_path,
    )

    # Minimal spec for run_step compatibility (no validation needed)
    stub_spec = {"run_name": run_name}

    while not dag.is_complete() and not dag.has_failed():
        ready = dag.get_ready_steps()
        if not ready:
            if dag.has_failed():
                break
            time.sleep(1)
            continue

        with ThreadPoolExecutor(max_workers=len(ready)) as pool:
            futures = {
                pool.submit(run_step, step, stub_spec, output_dir, dag): step
                for step in ready
            }
            for future in as_completed(futures):
                step = futures[future]
                try:
                    future.result()
                except Exception as e:
                    step.status = Status.FAILED
                    step.error = f"Unexpected exception in step '{step.step_id}': {e}"
                    logger.exception("Unhandled exception in step '%s'", step.step_id)

        write_status(dag, output_dir, run_name, started)

    write_status(dag, output_dir, run_name, started)

    if dag.is_complete():
        logger.info("Pipeline '%s' completed successfully", run_name)
        return True
    else:
        logger.error("Pipeline '%s' failed", run_name)
        return False




def resolve_step_references(step: Step, dag: DAG, output_dir: str) -> None:
    """Resolve *_from references in step config to actual file paths.

    Templates use keys like 'start_frame_from: "image_gen.anchor"' to reference
    the output of another step. This function:
    1. Injects output_dir and constructs output_path from output_filename
    2. Finds all config keys ending in '_from'
    3. Looks up the referenced step's output path
    4. Sets the corresponding path key (e.g., 'start_frame_path')

    Array refs are also supported: if the value is a list of step IDs,
    each is resolved and the result is stored as a plural path key:
        "clips_from": ["upscale.shot_1", "upscale.shot_2"]
        → "clip_paths": ["/path/s1.mp4", "/path/s2.mp4"]
    """
    config = step.config

    # Inject output_dir for adapters that need it (Convention A: output_dir + output_filename)
    if "output_filename" in config:
        config["output_dir"] = output_dir
        # Also construct output_path for Convention B adapters (ffmpeg, tts, music, pil_render)
        if "output_path" not in config:
            config["output_path"] = os.path.join(output_dir, config["output_filename"])

    from_keys = [k for k in config if k.endswith("_from")]

    for from_key in from_keys:
        ref_value = config[from_key]

        # Array refs: list of step IDs → list of output paths
        if isinstance(ref_value, list):
            resolved_paths = []
            for ref_step_id in ref_value:
                ref_step = dag.steps.get(ref_step_id)
                if ref_step and ref_step.output:
                    resolved_paths.append(ref_step.output)
            # "clips_from" → "clip_paths", "reference_images_from" → "reference_image_paths"
            base = from_key.replace("_from", "")
            if base.endswith("s"):
                target_key = f"{base[:-1]}_paths"
            else:
                target_key = f"{base}_paths"
            config[target_key] = resolved_paths
            continue

        # Single ref: string step ID → single output path
        ref_step_id = ref_value
        ref_step = dag.steps.get(ref_step_id)
        if not ref_step or not ref_step.output:
            continue

        target_key = from_key.replace("_from", "_path")
        config[target_key] = ref_step.output


def _log_step_spend(step: Step, spec: dict, output_dir: str) -> None:
    """Log spend for a completed step."""
    run_name = spec.get("run_name", "unnamed")
    try:
        log_spend(step.adapter_name, step.step_id, run_name, output_dir)
    except Exception as e:
        logging.getLogger("workflow.engine").warning(
            "Failed to log spend for step '%s': %s", step.step_id, e,
        )


def run_step(step: Step, spec: dict, output_dir: str, dag: DAG | None = None) -> None:
    """Execute a single step: submit, poll until done, download result."""
    step_logger = logging.getLogger(f"workflow.step.{step.step_id}")
    step_logger.info(
        "Starting step '%s' with adapter '%s'",
        step.step_id, step.adapter_name,
    )

    # Resolve any *_from references to actual file paths
    if dag is not None:
        resolve_step_references(step, dag, output_dir)

    # Check asset cache — skip generation if recursive cache key matches (includes upstream deps)
    from workflow.asset_cache import UNCACHEABLE_ADAPTERS
    if step.adapter_name in UNCACHEABLE_ADAPTERS:
        step_logger.debug("Skipping cache (uncacheable adapter '%s')", step.adapter_name)
    else:
        cached_output = check_cache(step)
        if cached_output:
            step.output = cached_output
            step.status = Status.COMPLETED
            step.duration_s = 0.0
            step.cache_hit = True
            step_logger.info(
                "Cache hit for step '%s' -> %s",
                step.step_id, cached_output,
            )
            return
        step_logger.info("Cache miss for step '%s'", step.step_id)

    try:
        adapter = get_adapter(step.adapter_name)
    except ValueError as e:
        step.status = Status.FAILED
        step.error = (
            f"Adapter '{step.adapter_name}' not found for step '{step.step_id}'. "
            f"Check that the adapter module exists and is registered. Original error: {e}"
        )
        step_logger.error("Adapter lookup failed: %s", step.error)
        return

    # Adapter health check for expensive steps (cost > $0.50)
    step_cost = COST_PER_STEP.get(step.adapter_name, 0.0)
    if step_cost > 0.50:
        if not adapter.health_check():
            step.status = Status.FAILED
            step.error = (
                f"Adapter health check failed for {step.adapter_name}. "
                f"API may be down or key missing."
            )
            step_logger.error("Health check failed: %s", step.error)
            return

    # Inject prompt logging context so adapters can call self.log_prompt()
    prompts_dir = os.path.join(output_dir, "prompts")
    step.config["_step_id"] = step.step_id
    step.config["_prompt_log_dir"] = prompts_dir

    start_time = time.time()
    step.status = Status.RUNNING

    try:
        step.job_id = adapter.submit(step.config)
    except Exception as e:
        step.status = Status.FAILED
        step.error = (
            f"Failed to submit step '{step.step_id}' to adapter '{step.adapter_name}': {e}"
        )
        step.duration_s = time.time() - start_time
        step_logger.error("Submit failed: %s", step.error)
        return

    if adapter.is_sync:
        step.output = step.job_id  # sync adapters return the path directly
        step.status = Status.COMPLETED
        step.duration_s = time.time() - start_time
        _log_step_spend(step, spec, output_dir)
        save_cache(step, step.output)
        step_logger.info(
            "Step '%s' completed (sync) in %.1fs -> %s",
            step.step_id, step.duration_s, step.output,
        )
        return

    # Poll async adapter
    step_logger.info(
        "Step '%s' submitted as job '%s', polling (timeout: %ds)...",
        step.step_id, step.job_id, adapter.timeout_seconds,
    )

    while True:
        elapsed = time.time() - start_time
        if elapsed > adapter.timeout_seconds:
            step.status = Status.FAILED
            step.error = (
                f"Step '{step.step_id}' timed out after {elapsed:.0f}s "
                f"(adapter '{step.adapter_name}' timeout: {adapter.timeout_seconds}s). "
                f"Job ID: {step.job_id}"
            )
            step.duration_s = elapsed
            step_logger.error("Timeout: %s", step.error)
            return

        try:
            status, meta = adapter.poll(step.job_id)
        except Exception as e:
            step.status = Status.FAILED
            step.error = (
                f"Poll error for step '{step.step_id}' "
                f"(adapter '{step.adapter_name}', job '{step.job_id}'): {e}"
            )
            step.duration_s = time.time() - start_time
            step_logger.error("Poll failed: %s", step.error)
            return

        if status == Status.COMPLETED:
            try:
                step.output = adapter.get_result(step.job_id)
            except Exception as e:
                step.status = Status.FAILED
                step.error = (
                    f"Failed to retrieve result for step '{step.step_id}' "
                    f"(adapter '{step.adapter_name}', job '{step.job_id}'): {e}"
                )
                step.duration_s = time.time() - start_time
                step_logger.error("Result retrieval failed: %s", step.error)
                return

            step.status = Status.COMPLETED
            step.duration_s = time.time() - start_time
            _log_step_spend(step, spec, output_dir)
            save_cache(step, step.output)
            step_logger.info(
                "Step '%s' completed in %.1fs -> %s",
                step.step_id, step.duration_s, step.output,
            )
            return

        if status == Status.FAILED:
            step.status = Status.FAILED
            step.error = (
                f"Step '{step.step_id}' failed "
                f"(adapter '{step.adapter_name}', job '{step.job_id}'): "
                f"{meta.get('error', 'Unknown error from adapter')}"
            )
            step.duration_s = time.time() - start_time
            step_logger.error("Adapter reported failure: %s", step.error)
            return

        time.sleep(8)


def retry_step(step: Step, spec: dict, output_dir: str, retry_policy: dict, dag: DAG | None = None) -> bool:
    """Attempt to retry a failed step. Returns True if retry succeeded."""
    max_retries = retry_policy.get("max_retries", 2)
    on_failure = retry_policy.get("on_failure", "retry")
    backoff = retry_policy.get("backoff", "exponential")

    if step.retries >= max_retries:
        logger.warning(
            "Step '%s' exhausted all %d retries", step.step_id, max_retries,
        )
        return False

    step.retries += 1
    logger.info(
        "Retrying step '%s' (attempt %d/%d, policy: %s)",
        step.step_id, step.retries, max_retries, on_failure,
    )

    # Backoff
    if backoff == "exponential":
        wait = 30 * (2 ** (step.retries - 1))
    else:
        wait = 30
    logger.debug("Backoff: waiting %ds before retry", wait)
    time.sleep(wait)

    # Swap fallback if configured
    if on_failure == "swap_fallback" and step.retries > 1:
        models = spec.get("models", {})
        for category in models.values():
            if isinstance(category, dict) and category.get("adapter") == step.adapter_name:
                fallback = category.get("fallback")
                if fallback:
                    logger.info(
                        "Swapping adapter for step '%s': %s -> %s",
                        step.step_id, step.adapter_name, fallback,
                    )
                    step.adapter_name = fallback
                    break

    # Reset and retry
    step.status = Status.PENDING
    step.error = None
    run_step(step, spec, output_dir, dag)
    return step.status == Status.COMPLETED


def restore_dag_from_status(dag: DAG, status: dict, output_dir: str,
                             resume_step: str | None = None,
                             override_adapter: str | None = None) -> tuple[list, list]:
    """Restore completed steps from a previous run's status.json into a DAG.

    Marks completed steps as COMPLETED and sets their output paths.
    Resets failed/pending steps so they will be re-executed.

    If resume_step is given, only that step (and its dependents) are reset.
    If override_adapter is given, use it for the resumed step.

    Returns (fallbacks_used, errors) carried over from the previous run.
    """
    steps_status = status.get("steps", {})
    fallbacks_used = status.get("fallbacks_used", [])

    # Determine which steps to reset
    if resume_step:
        # Reset only the specified step and anything that depends on it (transitively)
        steps_to_reset = {resume_step}
        changed = True
        while changed:
            changed = False
            for step_id, step in dag.steps.items():
                if step_id in steps_to_reset:
                    continue
                if any(dep in steps_to_reset for dep in step.depends_on):
                    steps_to_reset.add(step_id)
                    changed = True
    else:
        # Reset all non-completed steps
        steps_to_reset = {
            step_id for step_id, info in steps_status.items()
            if info.get("status") != "completed"
        }
        # Also reset steps not in status (new steps added to spec)
        for step_id in dag.steps:
            if step_id not in steps_status:
                steps_to_reset.add(step_id)

    restored = 0
    for step_id, step in dag.steps.items():
        if step_id in steps_to_reset:
            step.status = Status.PENDING
            step.error = None
            step.retries = 0
            if step_id == resume_step and override_adapter:
                step.adapter_name = override_adapter
            continue

        info = steps_status.get(step_id)
        if info and info.get("status") == "completed" and info.get("output"):
            step.status = Status.COMPLETED
            step.output = info["output"]
            step.duration_s = info.get("duration_s", 0)
            restored += 1

    logger.info(
        "Restored %d completed steps, %d steps to re-run",
        restored, len(steps_to_reset),
    )

    # Clear old errors for steps being re-run
    prev_errors = [
        e for e in status.get("errors", [])
        if e.get("step") not in steps_to_reset
    ]

    return fallbacks_used, prev_errors


def execute(spec: dict, output_dir: str, resume_status: dict | None = None,
            resume_step: str | None = None, override_adapter: str | None = None) -> bool:
    """Execute the full DAG with parallel step execution and retry logic.

    If resume_status is provided, restore completed steps from a previous run
    and only re-execute failed/pending steps.
    """
    # Validate spec before execution
    validation_errors = validate_spec(spec)
    if validation_errors:
        logger.error("Spec validation failed with %d error(s):", len(validation_errors))
        for err in validation_errors:
            logger.error("  - %s", err)
        # Write a wakeup with validation errors
        run_name = spec.get("run_name", "unnamed")
        error_msg = "Validation failed: " + "; ".join(validation_errors)
        write_wakeup(output_dir, run_name, "failed", error=error_msg)
        print_wakeup(run_name, "failed")
        return False

    # Log full cost estimate (before cache — worst case)
    cost = estimate_cost(spec)
    logger.info("Estimated cost (before cache): $%.2f USD", cost["total"])

    # Resolve all adapter names and stamp into spec so it's fully self-contained.
    # This means the saved production_spec.json can reproduce the exact same run.
    spec["models"] = resolve_all(spec)
    logger.info(
        "Resolved models: %s",
        {cat: cfg["adapter"] for cat, cfg in spec["models"].items()},
    )

    # Save the resolved spec to the output dir
    os.makedirs(output_dir, exist_ok=True)
    spec_path = os.path.join(output_dir, "production_spec.json")
    with open(spec_path, "w") as f:
        json.dump(spec, f, indent=2)
    logger.info("Saved resolved spec to %s", spec_path)

    dag = build_dag(spec)
    run_name = spec.get("run_name", "unnamed")
    retry_policy = spec.get("retry_policy", {})
    started = datetime.now(timezone.utc).isoformat()
    fallbacks_used = []
    errors = []

    # Save the compiled pipeline JSON for replayability/inspection
    pipeline_json = dag.to_json(metadata={"run_name": run_name, "output_dir": output_dir})
    pipeline_path = os.path.join(output_dir, "pipeline.json")
    with open(pipeline_path, "w") as f:
        json.dump(pipeline_json, f, indent=2)
    logger.info("Saved pipeline JSON to %s", pipeline_path)

    # Compute cache keys for all nodes
    from workflow.asset_cache import recursive_cache_key
    for step_id in dag.steps:
        dag.steps[step_id].cache_key = recursive_cache_key(step_id, dag)

    # Cache-aware budget cap — only count steps that will actually run
    from workflow.cost import estimate_dag_cost
    dag_cost = estimate_dag_cost(dag)
    if dag_cost["cached_steps"] > 0:
        logger.info(
            "Cache: %d/%d steps cached, actual cost: $%.2f USD",
            dag_cost["cached_steps"], dag_cost["total_steps"], dag_cost["total"],
        )
    cost_estimate = dag_cost

    profile = spec.get("profile", "production")
    default_budget = 25.0 if profile == "production" else 10.0
    max_budget = spec.get("max_budget", default_budget)
    if max_budget is not None and dag_cost["total"] > max_budget:
        error_msg = (
            f"This run would cost ~${dag_cost['total']:.2f}, which is over the "
            f"${max_budget:.2f} safety limit. You can: reduce the number of shots, "
            f"switch to cheaper models (profile: 'cheap'), or raise max_budget in the spec."
        )
        logger.error(error_msg)
        write_wakeup(output_dir, run_name, "failed", error=error_msg)
        print_wakeup(run_name, "failed")
        return False

    # Resume: restore completed steps from previous run
    if resume_status:
        fallbacks_used, errors = restore_dag_from_status(
            dag, resume_status, output_dir, resume_step, override_adapter,
        )
        # Preserve the original start time
        started = resume_status.get("started", started)

    os.makedirs(output_dir, exist_ok=True)

    # Dump all prompts before execution so they can be reviewed
    prompts_dir = os.path.join(output_dir, "prompts")
    dump_prompts(dag, prompts_dir)
    logger.info(
        "Prompts dumped to %s/ — review before generation starts",
        prompts_dir,
    )

    logger.info(
        "Starting workflow '%s' (%s) with %d steps",
        run_name, spec.get("video_type"), len(dag.steps),
    )

    while not dag.is_complete() and not dag.has_failed():
        ready = dag.get_ready_steps()
        if not ready:
            if dag.has_failed():
                break
            time.sleep(1)
            continue

        logger.info(
            "Running %d ready step(s): %s",
            len(ready), ", ".join(s.step_id for s in ready),
        )

        # Run ready steps in parallel
        with ThreadPoolExecutor(max_workers=len(ready)) as pool:
            futures = {
                pool.submit(run_step, step, spec, output_dir, dag): step
                for step in ready
            }
            for future in as_completed(futures):
                step = futures[future]
                try:
                    future.result()
                except Exception as e:
                    step.status = Status.FAILED
                    step.error = (
                        f"Unexpected exception in step '{step.step_id}' "
                        f"(adapter '{step.adapter_name}'): {e}"
                    )
                    logger.exception(
                        "Unhandled exception in step '%s'", step.step_id,
                    )

                # Handle failures with retry
                if step.status == Status.FAILED:
                    original_adapter = step.adapter_name
                    if retry_step(step, spec, output_dir, retry_policy, dag):
                        if step.adapter_name != original_adapter:
                            fallbacks_used.append({
                                "step": step.step_id,
                                "from": original_adapter,
                                "to": step.adapter_name,
                            })
                    else:
                        errors.append({
                            "step": step.step_id,
                            "error": step.error,
                            "retries": step.retries,
                        })

        # Update status after each batch
        write_status(dag, output_dir, run_name, started, fallbacks_used, errors, cost_estimate)

        # Quality gate: pause after frames are ready so you can review before
        # spending on video generation. Auto-enables when any video adapter costs
        # $1+/clip, unless explicitly disabled with "quality_gate": false.
        quality_gate = spec.get("quality_gate")
        if quality_gate is None:
            # Auto-enable: check if any video_gen step uses an expensive adapter
            from workflow.cost import COST_PER_STEP
            quality_gate = any(
                COST_PER_STEP.get(s.adapter_name, 0) >= 1.0
                for sid, s in dag.steps.items()
                if sid.startswith("video_gen")
            )
        if quality_gate:
            gate_path = os.path.join(output_dir, "quality_gate.json")
            all_image_done = all(
                s.status == Status.COMPLETED
                for sid, s in dag.steps.items()
                if sid.startswith("image_gen")
            )
            any_video_pending = any(
                s.status == Status.PENDING
                for sid, s in dag.steps.items()
                if sid.startswith("video_gen")
            )
            has_image_steps = any(
                sid.startswith("image_gen") for sid in dag.steps
            )
            gate_approved = False
            if os.path.exists(gate_path):
                try:
                    with open(gate_path) as gf:
                        gate_data = json.load(gf)
                    gate_approved = gate_data.get("status") == "approved"
                except (json.JSONDecodeError, OSError):
                    pass

            if has_image_steps and all_image_done and any_video_pending and not gate_approved:
                # Collect frame paths from completed image_gen steps
                frame_paths = [
                    s.output for sid, s in dag.steps.items()
                    if sid.startswith("image_gen") and s.output
                ]
                gate_data = {
                    "status": "waiting",
                    "frames": frame_paths,
                    "message": (
                        "Your frames are ready for review! Take a look and make "
                        "sure the characters and scenes look right before we "
                        "spend on video generation. When you're happy, approve "
                        "to continue."
                    ),
                }
                with open(gate_path, "w") as gf:
                    json.dump(gate_data, gf, indent=2)
                logger.info(
                    "Pausing for frame review — %d frame(s) ready at %s/. "
                    "Review them, then resume with --retry --approve-gate to continue to video generation.",
                    len(frame_paths), output_dir,
                )
                return False

    # Final status
    write_status(dag, output_dir, run_name, started, fallbacks_used, errors, cost_estimate)

    # Compute actual spend for this run from the spend log
    from workflow.spend_log import SPEND_LOG_PATH
    run_actual_spend = 0.0
    if os.path.exists(SPEND_LOG_PATH):
        try:
            with open(SPEND_LOG_PATH, "r") as _f:
                _all_entries = json.load(_f)
            run_actual_spend = sum(
                e.get("cost_usd", 0.0)
                for e in _all_entries
                if e.get("run_name") == run_name
            )
        except (json.JSONDecodeError, ValueError):
            pass
    logger.info(
        "Spend summary for '%s': actual $%.2f (estimated $%.2f)",
        run_name, run_actual_spend, cost_estimate.get("total", 0),
    )

    # Wakeup
    if dag.is_complete():
        final_path = os.path.join(output_dir, spec.get("output", {}).get("final_filename", "final.mp4"))
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds()
        write_wakeup(output_dir, run_name, "completed", output_path=final_path)
        print_wakeup(run_name, "completed", output_path=final_path)
        logger.info(
            "Workflow '%s' completed in %.1fs | Estimated: $%.2f | Actual: $%.2f -> %s",
            run_name, elapsed, cost_estimate.get("total", 0), run_actual_spend, final_path,
        )
        return True
    else:
        error_msg = "; ".join(e.get("error", "?") for e in errors)
        write_wakeup(output_dir, run_name, "failed", error=error_msg)
        print_wakeup(run_name, "failed")
        logger.error("Workflow '%s' failed: %s", run_name, error_msg)
        return False


def main():
    parser = argparse.ArgumentParser(description="Workflow engine")
    parser.add_argument("--spec", help="Path to production spec JSON")
    parser.add_argument("--background", action="store_true", help="Run in background")
    parser.add_argument("--validate", action="store_true", help="Validate spec only (don't run)")
    parser.add_argument("--dump-prompts", action="store_true", help="Dump all prompts to review (don't run)")
    parser.add_argument("--status", help="Path to status.json to check")
    parser.add_argument("--retry", help="Path to status.json to resume from")
    parser.add_argument("--step", help="Step ID to retry (only re-runs this step and its dependents)")
    parser.add_argument("--adapter", help="Override adapter for the retried step")
    parser.add_argument("--approve-gate", action="store_true", help="Approve quality gate and continue execution")
    parser.add_argument("--pipeline", help="Path to pre-compiled pipeline.json to execute")
    parser.add_argument("--dry-run", action="store_true", help="Validate pipeline without executing")
    parser.add_argument("--visualize", action="store_true", help="Generate Mermaid DAG markdown (don't run)")
    args = parser.parse_args()

    if args.status:
        status = read_status(os.path.dirname(args.status))
        print(json.dumps(status, indent=2))
        return

    # --pipeline mode: execute a pre-compiled pipeline JSON
    if args.pipeline:
        output_dir = None
        if args.spec:
            spec = load_spec(args.spec)
            output_dir = spec.get("output", {}).get("dir")

        # --pipeline --dump-prompts: extract prompts from pipeline.json without running
        if args.dump_prompts:
            with open(args.pipeline) as f:
                pipeline = json.load(f)
            dag = DAG.from_json(pipeline)
            prompts_dir = output_dir or os.path.join(os.path.dirname(args.pipeline), "prompts")
            if not os.path.isabs(prompts_dir):
                prompts_dir = os.path.join(os.path.dirname(args.pipeline), "prompts")
            dump_prompts(dag, prompts_dir)
            from workflow.cost import estimate_pipeline_cost
            cost = estimate_pipeline_cost(pipeline)
            print(json.dumps({
                "prompts_dir": prompts_dir,
                "files": sorted(os.listdir(prompts_dir)),
                "steps": len(dag.steps),
                "cost": cost,
            }, indent=2))
            sys.exit(0)

        # --pipeline --visualize: generate Mermaid DAG markdown without running
        if args.visualize:
            with open(args.pipeline) as f:
                pipeline = json.load(f)
            dag = DAG.from_json(pipeline)
            from workflow.compiler import format_mermaid_md
            md = format_mermaid_md(dag, pipeline)
            md_path = os.path.splitext(args.pipeline)[0] + ".md"
            with open(md_path, "w") as f:
                f.write(md)
            print(md)
            print(f"\nSaved to {md_path}")
            sys.exit(0)

        setup_logging(output_dir)
        success = execute_pipeline(
            args.pipeline, output_dir=output_dir,
            dry_run=args.dry_run, resume_from=args.retry,
        )
        sys.exit(0 if success else 1)

    # --retry mode: resume a failed run from its status.json
    if args.retry:
        resume_status = read_status(os.path.dirname(args.retry))
        # Require --spec to know the original production spec
        if not args.spec:
            print("Error: --retry requires --spec (path to the production spec)", file=sys.stderr)
            sys.exit(1)
        spec = load_spec(args.spec)
        output_dir = spec.get("output", {}).get("dir", f"outputs/runs/{spec.get('run_name', 'unnamed')}")
        setup_logging(output_dir)

        # --approve-gate: write approval to the gate file before resuming
        if args.approve_gate:
            gate_path = os.path.join(output_dir, "quality_gate.json")
            gate_data = {"status": "approved"}
            if os.path.exists(gate_path):
                try:
                    with open(gate_path) as gf:
                        gate_data = json.load(gf)
                    gate_data["status"] = "approved"
                except (json.JSONDecodeError, OSError):
                    gate_data = {"status": "approved"}
            with open(gate_path, "w") as gf:
                json.dump(gate_data, gf, indent=2)
            logger.info("Quality gate approved at %s", gate_path)

        if args.background:
            pid = os.fork()
            if pid > 0:
                print(json.dumps({"pid": pid, "output_dir": output_dir, "run_name": spec.get("run_name")}))
                sys.exit(0)
            os.setsid()

        success = execute(
            spec, output_dir,
            resume_status=resume_status,
            resume_step=args.step,
            override_adapter=args.adapter,
        )
        sys.exit(0 if success else 1)

    if not args.spec:
        parser.print_help()
        sys.exit(1)

    spec = load_spec(args.spec)
    output_dir = spec.get("output", {}).get("dir", f"outputs/runs/{spec.get('run_name', 'unnamed')}")

    # --validate: check spec and print results without running
    if args.validate:
        errors = validate_spec(spec)
        if errors:
            print(json.dumps({"valid": False, "errors": errors}, indent=2))
            sys.exit(1)
        else:
            cost = estimate_cost(spec)
            print(json.dumps({"valid": True, "errors": [], "cost": cost}, indent=2))
            sys.exit(0)

    # --dump-prompts: build DAG, dump all prompts, exit without running
    if args.dump_prompts:
        errors = validate_spec(spec)
        if errors:
            print(json.dumps({"valid": False, "errors": errors}, indent=2))
            sys.exit(1)
        dag = build_dag(spec)
        prompts_dir = os.path.join(output_dir, "prompts")
        dump_prompts(dag, prompts_dir)
        cost = estimate_cost(spec)
        print(json.dumps({
            "prompts_dir": prompts_dir,
            "files": sorted(os.listdir(prompts_dir)),
            "steps": len(dag.steps),
            "cost": cost,
        }, indent=2))
        sys.exit(0)

    # --visualize: build DAG from spec, generate Mermaid markdown
    if args.visualize:
        errors = validate_spec(spec)
        if errors:
            print(json.dumps({"valid": False, "errors": errors}, indent=2))
            sys.exit(1)
        dag = build_dag(spec)
        pipeline = compile_spec(spec)
        from workflow.compiler import format_mermaid_md
        md = format_mermaid_md(dag, pipeline)
        md_path = os.path.join(output_dir, "pipeline.md")
        os.makedirs(output_dir, exist_ok=True)
        with open(md_path, "w") as f:
            f.write(md)
        print(md)
        print(f"\nSaved to {md_path}")
        sys.exit(0)

    # Set up logging (stderr + file in output dir)
    setup_logging(output_dir)

    if args.background:
        pid = os.fork()
        if pid > 0:
            print(json.dumps({"pid": pid, "output_dir": output_dir, "run_name": spec.get("run_name")}))
            sys.exit(0)
        # Child process continues
        os.setsid()

    success = execute(spec, output_dir)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
