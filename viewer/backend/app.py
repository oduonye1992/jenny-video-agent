"""Pipeline Viewer — FastAPI backend.

Serves run metadata, assets, and supports prompt editing + re-runs.
"""

import json
import logging
import os
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

logger = logging.getLogger("viewer")

# Resolve project root (two levels up from viewer/backend/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Add project root to path for plan_schema import
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
RUNS_DIR = OUTPUTS_DIR / "runs"
CONCEPTS_DIR = OUTPUTS_DIR / "concepts"

app = FastAPI(title="Pipeline Viewer", version="0.1.0")

# Gzip compress all responses > 500 bytes (huge win for JSON + text over tunnels)
app.add_middleware(GZipMiddleware, minimum_size=500)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _claude_env() -> dict[str, str]:
    """Build an env dict for spawning Claude Code CLI.

    Strips CLAUDECODE to avoid nested-session detection.
    """
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    return env


# ---------------------------------------------------------------------------
# CDN Layer — lazy Supabase upload for remote access
# ---------------------------------------------------------------------------

CDN_BUCKET = "viewer_assets"
CDN_ENABLED = bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SECRET_KEY"))
_cdn_pool = ThreadPoolExecutor(max_workers=3)
_cdn_cache_lock = threading.Lock()
# In-flight uploads — prevents duplicate uploads for the same file
_cdn_inflight: set[str] = set()


@app.on_event("startup")
def _ensure_cdn_bucket():
    """Create the CDN bucket on startup if it doesn't exist."""
    if not CDN_ENABLED:
        logger.info("CDN disabled (no SUPABASE_URL/SUPABASE_SECRET_KEY)")
        return
    try:
        from workflow.adapters._supabase import _get_client
        client = _get_client()
        buckets = client.storage.list_buckets()
        if not any(b.name == CDN_BUCKET for b in buckets):
            client.storage.create_bucket(CDN_BUCKET, options={"public": True})
            logger.info(f"CDN: created bucket '{CDN_BUCKET}'")
        else:
            logger.info(f"CDN: bucket '{CDN_BUCKET}' exists")
    except Exception as e:
        logger.warning(f"CDN: bucket check failed — {e}. Uploads may fail.")


def _cdn_cache_path(directory: Path) -> Path:
    return directory / ".cdn_cache.json"


def _read_cdn_cache(directory: Path) -> dict[str, str]:
    cache_file = _cdn_cache_path(directory)
    if cache_file.exists():
        try:
            with open(cache_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _write_cdn_cache(directory: Path, cache: dict[str, str]) -> None:
    cache_file = _cdn_cache_path(directory)
    with open(cache_file, "w") as f:
        json.dump(cache, f, indent=2)


def _cdn_upload_file(local_path: Path, remote_key: str) -> str | None:
    """Upload a single file to Supabase and return the public URL."""
    try:
        from workflow.adapters._supabase import upload_to_supabase
        url = upload_to_supabase(CDN_BUCKET, str(local_path), remote_key)
        return url
    except Exception as e:
        logger.warning(f"CDN upload failed for {local_path.name}: {e}")
        return None


def _cdn_upload_background(directory: Path, filename: str, remote_key: str) -> None:
    """Background task: upload file, update cache."""
    local_path = directory / filename
    if not local_path.exists():
        return

    url = _cdn_upload_file(local_path, remote_key)
    if url:
        with _cdn_cache_lock:
            cache = _read_cdn_cache(directory)
            cache[filename] = url
            _write_cdn_cache(directory, cache)
            _cdn_inflight.discard(str(local_path))
        logger.info(f"CDN: uploaded {filename} -> {url[:80]}...")


def _resolve_asset_url(
    directory: Path,
    filename: str,
    local_url: str,
    cdn_prefix: str,
) -> str:
    """Return CDN URL if cached, else queue background upload and return local URL.

    cdn_prefix: e.g. "runs/my-run" or "concepts/my-concept/run-kling"
    """
    if not CDN_ENABLED:
        return local_url

    # Check cache first (fast path, no lock needed for reads)
    cache = _read_cdn_cache(directory)
    if filename in cache:
        return cache[filename]

    # Queue background upload if not already in-flight
    local_path = directory / filename
    cache_key = str(local_path)
    with _cdn_cache_lock:
        if cache_key not in _cdn_inflight:
            _cdn_inflight.add(cache_key)
            remote_key = f"{cdn_prefix}/{filename}"
            _cdn_pool.submit(_cdn_upload_background, directory, filename, remote_key)

    return local_url


def _resolve_assets(
    directory: Path,
    local_base: str,
    cdn_prefix: str,
) -> dict[str, str]:
    """Discover media assets in a directory and return filename → URL mapping.

    Uses CDN URLs when available, local URLs as fallback.
    """
    assets = {}
    for f in directory.iterdir():
        if f.suffix in (".png", ".jpg", ".jpeg", ".mp4", ".mp3", ".webm"):
            local_url = f"{local_base}/{f.name}"
            assets[f.name] = _resolve_asset_url(directory, f.name, local_url, cdn_prefix)
    return assets


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict | None:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def _list_prompts(run_dir: Path) -> dict[str, str]:
    """Read all .txt prompt files from the prompts/ subfolder."""
    prompts_dir = run_dir / "prompts"
    result = {}
    if prompts_dir.is_dir():
        for f in sorted(prompts_dir.iterdir()):
            if f.suffix == ".txt":
                result[f.stem] = f.read_text()
    return result


VERSION_RE = re.compile(r"^(.+)_v(\d+)(\..+)$")


def _next_version(run_dir: Path, filename: str) -> int:
    """Find the next version number for a file in a run directory.

    Scans for existing _v{N} files and returns N+1, or 1 if none exist.
    """
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    max_v = 0
    for f in run_dir.iterdir():
        m = VERSION_RE.match(f.name)
        if m and m.group(1) == stem and m.group(3) == suffix:
            max_v = max(max_v, int(m.group(2)))
    return max_v + 1


def _version_step_outputs(run_dir: Path, step_id: str, pipeline: dict, status: dict) -> list[str]:
    """Version existing output files for a step before re-running it.

    Renames the_confession.mp4 → the_confession_v1.mp4, etc.
    Also versions related files (upscaled, thumbnails, first frames).
    Returns list of versioned filenames.
    """
    versioned = []

    # Find output filename from status or pipeline config
    step_status = status.get("steps", {}).get(step_id, {})
    output_path = step_status.get("output", "")
    output_file = Path(output_path).name if output_path else None

    if not output_file:
        # Fall back to pipeline config
        for node in pipeline.get("nodes", []):
            if node.get("id") == step_id:
                output_file = node.get("config", {}).get("output_filename")
                break

    if not output_file:
        return versioned

    # Collect related files to version (output + upscaled + thumbnails + first frames)
    stem = Path(output_file).stem
    suffix = Path(output_file).suffix
    related = [output_file]

    # Common derived files
    for pattern in [
        f"{stem}_upscaled{suffix}",      # upscaled version
        f"{stem}{suffix}.thumb.png",       # thumbnail
        f"{stem}_first.png",               # first frame extract
        f"{stem}_last.png",                # last frame extract
    ]:
        if (run_dir / pattern).exists():
            related.append(pattern)

    # Also check for upscale step output
    upscale_id = step_id.replace("video_gen", "upscale")
    upscale_status = status.get("steps", {}).get(upscale_id, {})
    if upscale_status.get("output"):
        upscale_file = Path(upscale_status["output"]).name
        if upscale_file not in related:
            related.append(upscale_file)

    for fname in related:
        fpath = run_dir / fname
        if not fpath.exists():
            continue
        fstem = Path(fname).stem
        fsuffix = Path(fname).suffix
        # Handle double-extension like .mp4.thumb.png
        if ".thumb" in fname:
            fstem = fname.split(".")[0]
            fsuffix = "." + ".".join(fname.split(".")[1:])
        v = _next_version(run_dir, f"{fstem}{fsuffix}")
        versioned_name = f"{fstem}_v{v}{fsuffix}"
        fpath.rename(run_dir / versioned_name)
        versioned.append(versioned_name)

    return versioned


def _find_versions(run_dir: Path, filename: str, asset_base: str, cdn_prefix: str = "") -> list[dict]:
    """Find all versioned copies of a file in a run directory.

    Returns list of {version, url, modified} sorted oldest first.
    """
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    versions = []

    for f in run_dir.iterdir():
        m = VERSION_RE.match(f.name)
        if m and m.group(1) == stem and m.group(3) == suffix:
            local_url = f"{asset_base}/{f.name}"
            url = _resolve_asset_url(run_dir, f.name, local_url, cdn_prefix) if cdn_prefix else local_url
            versions.append({
                "version": int(m.group(2)),
                "url": url,
                "filename": f.name,
                "modified": f.stat().st_mtime,
            })

    versions.sort(key=lambda v: v["version"])
    return versions


def _resolve_run_dir(run_name: str) -> tuple[Path, str]:
    """Resolve a run name to its directory and asset base URL.

    Handles:
    1. Standard runs (outputs/runs/X)
    2. Concept-embedded runs with slash (concept/run-X)
    3. Concept-root runs (outputs/concepts/X with pipeline.json at root)
    """
    run_dir = RUNS_DIR / run_name
    asset_base = f"/api/assets/{run_name}"

    if not run_dir.is_dir() and "/" in run_name:
        concept_slug, sub_name = run_name.split("/", 1)
        # Handle runs/NNN path (new versioned layout)
        run_dir = CONCEPTS_DIR / concept_slug / sub_name
        asset_base = f"/api/concept-assets/{concept_slug}/{sub_name}"

    # Concept-root runs: pipeline.json lives directly in the concept folder (legacy)
    if not run_dir.is_dir():
        concept_root = CONCEPTS_DIR / run_name
        if concept_root.is_dir() and (concept_root / "pipeline.json").exists():
            run_dir = concept_root
            asset_base = f"/api/concept-assets/{run_name}"

    return run_dir, asset_base


def _find_concept_for_run(run_name: str, pipeline: dict, spec: dict | None) -> str | None:
    """Try to find the concept folder linked to a run.

    Strategy:
    1. Check pipeline.json for concept_dir field
    2. Search pipeline node configs for 'outputs/concepts/<slug>/' references
    3. Search spec reference_image paths
    4. Check if a concept folder contains a run/ subfolder matching run_name
    """
    # 1. Explicit field
    concept_dir = (pipeline or {}).get("concept_dir")
    if concept_dir:
        slug = Path(concept_dir).name
        if (CONCEPTS_DIR / slug).is_dir():
            return slug

    # 2. Scan pipeline configs for concept paths
    for node in (pipeline or {}).get("nodes", []):
        for val in node.get("config", {}).values():
            if isinstance(val, str) and "outputs/concepts/" in val:
                # Extract slug from path like "outputs/concepts/my-concept/character/ref.jpg"
                parts = val.split("outputs/concepts/")
                if len(parts) > 1:
                    slug = parts[1].split("/")[0]
                    if (CONCEPTS_DIR / slug).is_dir():
                        return slug

    # 3. Scan spec shots for reference_image paths
    if spec:
        for shot in spec.get("shots", []):
            ref = shot.get("reference_image", "")
            if "outputs/concepts/" in ref:
                slug = ref.split("outputs/concepts/")[1].split("/")[0]
                if (CONCEPTS_DIR / slug).is_dir():
                    return slug

    # 4. Check concept folders for run/ subdir matching run_name
    if CONCEPTS_DIR.is_dir():
        for d in CONCEPTS_DIR.iterdir():
            if d.is_dir():
                for sub in d.iterdir():
                    if sub.is_dir() and sub.name == run_name:
                        return d.name
                    # Also check run-* named subdirs
                    if sub.is_dir() and sub.name.startswith("run"):
                        pipeline_in_sub = _read_json(sub / "pipeline.json")
                        if pipeline_in_sub and pipeline_in_sub.get("run_name") == run_name:
                            return d.name

    return None


def _get_concept_data(slug: str) -> dict[str, Any] | None:
    """Read concept folder and return structured data for the viewer."""
    concept_dir = CONCEPTS_DIR / slug
    if not concept_dir.is_dir():
        return None

    result: dict[str, Any] = {"slug": slug, "path": str(concept_dir)}

    # Plan (structured JSON takes priority, fall back to markdown)
    plan_json_path = concept_dir / "plan.json"
    plan_md_path = concept_dir / "plan.md"
    if plan_json_path.exists():
        result["plan_json"] = _read_json(plan_json_path)
        # Also render markdown for display
        try:
            from workflow.plan_schema import Plan as PlanSchema
            plan_obj = PlanSchema.from_dict(result["plan_json"])
            result["plan"] = plan_obj.to_markdown()
        except Exception:
            result["plan"] = plan_md_path.read_text() if plan_md_path.exists() else None
    elif plan_md_path.exists():
        result["plan"] = plan_md_path.read_text()

    # Character
    char_dir = concept_dir / "character"
    if char_dir.is_dir():
        char_md = char_dir / "character.md"
        if char_md.exists():
            result["character_description"] = char_md.read_text()

        # Character reference photos
        char_assets = []
        cdn_prefix = f"concepts/{slug}/character"
        for f in sorted(char_dir.iterdir()):
            if f.suffix in (".png", ".jpg", ".jpeg"):
                local_url = f"/api/concept-assets/{slug}/character/{f.name}"
                char_assets.append({
                    "name": f.name,
                    "url": _resolve_asset_url(char_dir, f.name, local_url, cdn_prefix),
                })
        result["character_refs"] = char_assets

    # Frames (the creative iteration progression)
    frames_dir = concept_dir / "frames"
    if frames_dir.is_dir():
        frames = []
        for f in sorted(frames_dir.iterdir(), key=lambda p: p.stat().st_mtime):
            if f.suffix in (".png", ".jpg", ".jpeg"):
                # Read companion prompt file if exists
                prompt_file = frames_dir / f"{f.stem}_prompt.txt"
                prompt_json = frames_dir / f"{f.stem}_prompt.json"
                prompt = None
                if prompt_file.exists():
                    prompt = prompt_file.read_text()
                elif prompt_json.exists():
                    prompt = prompt_json.read_text()

                local_url = f"/api/concept-assets/{slug}/frames/{f.name}"
                frames.append({
                    "name": f.stem,
                    "url": _resolve_asset_url(frames_dir, f.name, local_url, f"concepts/{slug}/frames"),
                    "prompt": prompt,
                    "modified": f.stat().st_mtime,
                })
        result["frames"] = frames

    # Clips
    clips_dir = concept_dir / "clips"
    if clips_dir.is_dir():
        clips = []
        for f in sorted(clips_dir.iterdir(), key=lambda p: p.stat().st_mtime):
            if f.suffix in (".mp4", ".webm"):
                prompt_file = clips_dir / f"{f.stem}_prompt.txt"
                local_url = f"/api/concept-assets/{slug}/clips/{f.name}"
                clips.append({
                    "name": f.stem,
                    "url": _resolve_asset_url(clips_dir, f.name, local_url, f"concepts/{slug}/clips"),
                    "prompt": prompt_file.read_text() if prompt_file.exists() else None,
                    "modified": f.stat().st_mtime,
                })
        result["clips"] = clips

    # Voices
    voices_dir = concept_dir / "voices"
    if voices_dir.is_dir():
        voices = []
        for f in sorted(voices_dir.iterdir()):
            if f.suffix in (".mp3", ".wav"):
                local_url = f"/api/concept-assets/{slug}/voices/{f.name}"
                voices.append({
                    "name": f.stem,
                    "url": _resolve_asset_url(voices_dir, f.name, local_url, f"concepts/{slug}/voices"),
                })
        result["voices"] = voices

    # Shots descriptions
    shots_dir = concept_dir / "shots"
    if shots_dir.is_dir():
        shot_descs = {}
        for f in sorted(shots_dir.iterdir()):
            if f.suffix == ".md":
                shot_descs[f.stem] = f.read_text()
        result["shot_descriptions"] = shot_descs

    # Narration
    narration_path = concept_dir / "narration.md"
    if narration_path.exists():
        result["narration"] = narration_path.read_text()

    # Input (the original brief / source material)
    input_json = _read_json(concept_dir / "input.json")
    if input_json:
        result["input"] = input_json

    # Concept JSON (legacy)
    concept_json = _read_json(concept_dir / "concept.json")
    if concept_json:
        result["concept_json"] = concept_json

    # Collect video assets from all run subfolders (runs/001/, runs/002/, ...)
    # and from concept root (legacy flat layout)
    video_assets = []

    def _scan_run_videos(run_dir: Path, url_prefix: str, cdn_prefix: str, run_label: str):
        """Scan a run directory for video assets with prompt matching."""
        # Build step_id → output_filename mapping from this run's pipeline.json
        pipeline = _read_json(run_dir / "pipeline.json") or {}
        step_to_output: dict[str, str] = {}
        # Build output_filename → start_frame_url mapping from pipeline nodes
        output_to_anchor: dict[str, str] = {}
        output_to_anchor_prompt: dict[str, str | None] = {}
        for node in pipeline.get("nodes", []):
            config = node.get("config", {})
            out = config.get("output_filename")
            if out:
                step_to_output[node["id"]] = out
            # Map video_gen output → its start_frame_path, character_ref_frame_path, or start_frame_from (anchor image)
            sfp = config.get("start_frame_path") or config.get("character_ref_frame_path")
            # Resolve start_frame_from: dynamic dependency on another node's output
            if not sfp and config.get("start_frame_from"):
                ref_node_id = config["start_frame_from"]
                ref_output = step_to_output.get(ref_node_id)
                if ref_output:
                    candidate = run_dir / ref_output
                    if candidate.exists():
                        sfp = str(candidate)
            if out and sfp and node.get("id", "").startswith("video_gen"):
                # Convert local path to a URL via concept-assets
                sfp_path = Path(sfp)
                if sfp_path.exists():
                    # Path like .../outputs/concepts/<slug>/shots/shot_01/frame/anchor.png
                    try:
                        rel = sfp_path.relative_to(concept_dir)
                        output_to_anchor[out] = f"/api/concept-assets/{slug}/{rel}"
                    except ValueError:
                        pass
                    # Find companion prompt for the anchor
                    anchor_prompt = None
                    for ext in ("_prompt.json", "_prompt.txt"):
                        companion = sfp_path.parent / f"{sfp_path.stem}{ext}"
                        if companion.exists():
                            anchor_prompt = companion.read_text()
                            break
                    output_to_anchor_prompt[out] = anchor_prompt
                # Also map upscaled version → same anchor
                upscale_id = node["id"].replace("video_gen", "upscale")
                for n2 in pipeline.get("nodes", []):
                    if n2.get("id") == upscale_id:
                        up_out = n2.get("config", {}).get("output_filename")
                        if up_out:
                            output_to_anchor[up_out] = output_to_anchor.get(out, "")
                            output_to_anchor_prompt[up_out] = output_to_anchor_prompt.get(out)

        # Build output_filename → prompt mapping from this run's prompts/ directory
        output_to_prompt: dict[str, str] = {}
        prompts_dir = run_dir / "prompts"
        if prompts_dir.is_dir():
            for pf in prompts_dir.iterdir():
                if pf.suffix == ".json":
                    try:
                        prompt_data = json.loads(pf.read_text())
                        step_id = prompt_data.get("step_id", pf.stem)
                        prompt_text = prompt_data.get("payload", {}).get("prompt", "")
                        if step_id in step_to_output:
                            output_to_prompt[step_to_output[step_id]] = prompt_text
                        output_to_prompt[step_id] = prompt_text
                    except (json.JSONDecodeError, OSError):
                        pass

        for f in sorted(run_dir.iterdir(), key=lambda p: p.stat().st_mtime):
            if f.suffix not in (".mp4", ".webm"):
                continue
            local_url = f"{url_prefix}/{f.name}"
            prompt = None
            # Companion prompt file
            for ext in ("_prompt.json", "_prompt.txt"):
                companion = run_dir / f"{f.stem}{ext}"
                if companion.exists():
                    prompt = companion.read_text()
                    break
            # Pipeline → prompts mapping
            if not prompt and f.name in output_to_prompt:
                prompt = output_to_prompt[f.name]
            # Fuzzy match by beat name
            if not prompt:
                for step_id, prompt_text in output_to_prompt.items():
                    if not prompt_text or step_id.startswith("upscale"):
                        continue
                    beat = step_id.replace("video_gen_", "").replace("image_gen_", "")
                    if beat and beat in f.stem:
                        prompt = prompt_text
                        break
            # Final/upscaled files inherit prompt from source
            if not prompt and f.stem.startswith("final"):
                for step_id, prompt_text in output_to_prompt.items():
                    if prompt_text and not step_id.startswith("upscale"):
                        prompt = prompt_text
                        break

            # Anchor frame URL and prompt from pipeline start_frame_path
            anchor_url = output_to_anchor.get(f.name)
            anchor_prompt = output_to_anchor_prompt.get(f.name)

            video_assets.append({
                "filename": f.name,
                "url": _resolve_asset_url(run_dir, f.name, local_url, cdn_prefix),
                "prompt": prompt,
                "anchor_url": anchor_url,
                "anchor_prompt": anchor_prompt,
                "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
                "modified": f.stat().st_mtime,
                "run_label": run_label,
            })

    # Scan runs/ subfolders (new versioned layout)
    runs_dir = concept_dir / "runs"
    if runs_dir.is_dir():
        for run_sub in sorted(runs_dir.iterdir()):
            if run_sub.is_dir() and run_sub.name.isdigit():
                _scan_run_videos(
                    run_sub,
                    f"/api/concept-assets/{slug}/runs/{run_sub.name}",
                    f"concepts/{slug}/runs/{run_sub.name}",
                    f"Run {int(run_sub.name)}",
                )

    # Scan concept root for legacy flat layout videos
    _scan_run_videos(
        concept_dir,
        f"/api/concept-assets/{slug}",
        f"concepts/{slug}",
        "legacy",
    )
    # Remove legacy entries that are just duplicates (no videos at concept root in new layout)
    video_assets = [v for v in video_assets if v["run_label"] != "legacy" or not runs_dir.is_dir()]

    if video_assets:
        result["video_assets"] = video_assets

    # --- 5-stage flow artifacts ---

    # Creative (new flow — takes priority over plan.md)
    creative_json = _read_json(concept_dir / "creative.json")
    if creative_json:
        result["creative"] = creative_json
    creative_md = concept_dir / "creative.md"
    if creative_md.exists() and not result.get("plan"):
        result["plan"] = creative_md.read_text()

    # Director
    director_json = _read_json(concept_dir / "director.json")
    if director_json:
        result["director"] = director_json
    director_md = concept_dir / "director.md"
    if director_md.exists():
        result["director_md"] = director_md.read_text()

    # Per-shot anchors and prompts (shots/<shot_id>/frame/, shots/<shot_id>/prompts/)
    shots_dir = concept_dir / "shots"
    if shots_dir.is_dir():
        shot_details = []
        for shot_dir in sorted(shots_dir.iterdir()):
            if not shot_dir.is_dir():
                continue
            shot_id = shot_dir.name
            shot_info: dict[str, Any] = {"shot_id": shot_id}

            # Anchor frames with companion prompts
            frame_dir = shot_dir / "frame"
            if frame_dir.is_dir():
                anchors = []
                for f in sorted(frame_dir.iterdir()):
                    if f.suffix in (".png", ".jpg", ".jpeg"):
                        local_url = f"/api/concept-assets/{slug}/shots/{shot_id}/frame/{f.name}"
                        # Look for companion prompt
                        prompt = None
                        for ext in ("_prompt.json", "_prompt.txt"):
                            companion = frame_dir / f"{f.stem}{ext}"
                            if companion.exists():
                                prompt = companion.read_text()
                                break
                        anchors.append({
                            "name": f.stem,
                            "url": _resolve_asset_url(
                                frame_dir, f.name, local_url,
                                f"concepts/{slug}/shots/{shot_id}/frame",
                            ),
                            "prompt": prompt,
                        })
                shot_info["anchors"] = anchors

            # Prompts
            prompts_dir = shot_dir / "prompts"
            if prompts_dir.is_dir():
                shot_prompts = {}
                for f in sorted(prompts_dir.iterdir()):
                    if f.suffix in (".txt", ".json"):
                        shot_prompts[f.stem] = f.read_text()
                shot_info["prompts"] = shot_prompts

            shot_details.append(shot_info)

        if shot_details:
            result["shot_details"] = shot_details

    return result


def _get_run_summary(run_name: str) -> dict[str, Any]:
    run_dir, asset_base = _resolve_run_dir(run_name)

    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Run '{run_name}' not found")

    status = _read_json(run_dir / "status.json") or {}
    pipeline = _read_json(run_dir / "pipeline.json") or {}
    spec = _read_json(run_dir / "production_spec.json")
    prompts = _list_prompts(run_dir)

    # Discover asset files (with CDN resolution)
    cdn_prefix = f"runs/{run_name}"
    assets = _resolve_assets(run_dir, asset_base, cdn_prefix)

    # Build version history per node
    versions: dict[str, list[dict]] = {}
    for node in pipeline.get("nodes", []):
        node_id = node.get("id", "")
        step_status = status.get("steps", {}).get(node_id, {})
        output_path = step_status.get("output", "")
        output_file = Path(output_path).name if output_path else node.get("config", {}).get("output_filename")
        if output_file:
            v = _find_versions(run_dir, output_file, asset_base, cdn_prefix)
            if v:
                versions[node_id] = v

    # Find linked concept
    concept_slug = _find_concept_for_run(run_name, pipeline, spec)
    if not concept_slug and "/" in run_name:
        concept_slug = run_name.split("/")[0]
    concept = _get_concept_data(concept_slug) if concept_slug else None

    return {
        "run_name": run_name,
        "status": status,
        "pipeline": pipeline,
        "spec": spec,
        "prompts": prompts,
        "assets": assets,
        "versions": versions,
        "concept": concept,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _build_run_entry(d: Path, asset_prefix: str, concept_slug: str | None = None, cdn_prefix: str | None = None) -> dict:
    """Build a run list entry from a run directory."""
    status = _read_json(d / "status.json") or {}
    spec = _read_json(d / "production_spec.json")
    pipeline = _read_json(d / "pipeline.json") or {}

    if not concept_slug:
        concept_slug = _find_concept_for_run(d.name, pipeline, spec)

    thumb = None
    for candidate in ["final.mp4.thumb.png", "anchor_frame.png", "frame.png"]:
        if (d / candidate).exists():
            local_url = f"{asset_prefix}/{candidate}"
            thumb = _resolve_asset_url(d, candidate, local_url, cdn_prefix or f"runs/{d.name}") if CDN_ENABLED else local_url
            break

    return {
        "run_name": d.name,
        "complete": status.get("complete", False),
        "failed": status.get("failed", False),
        "elapsed_s": status.get("elapsed_s"),
        "cost": status.get("cost", {}).get("total"),
        "shot_count": len([n for n in pipeline.get("nodes", [])
                          if n.get("id", "").startswith("video_gen")]),
        "character_name": (spec or {}).get("character", {}).get("name"),
        "video_type": (spec or {}).get("video_type"),
        "started": status.get("started"),
        "thumbnail": thumb,
        "concept_slug": concept_slug,
        "run_dir": str(d),
    }


@app.get("/api/runs")
def list_runs():
    """List all runs — from outputs/runs/ and concept subfolders."""
    runs = []

    # 1. Standard runs in outputs/runs/
    if RUNS_DIR.is_dir():
        for d in RUNS_DIR.iterdir():
            if d.is_dir() and (d / "pipeline.json").exists():
                runs.append(_build_run_entry(d, f"/api/assets/{d.name}", cdn_prefix=f"runs/{d.name}"))

    # 2. Runs embedded in concept folders
    if CONCEPTS_DIR.is_dir():
        for concept_dir in CONCEPTS_DIR.iterdir():
            if not concept_dir.is_dir():
                continue
            # 2a. Versioned runs in runs/NNN/ subfolders (new layout)
            runs_sub = concept_dir / "runs"
            if runs_sub.is_dir():
                for run_num in sorted(runs_sub.iterdir()):
                    if run_num.is_dir() and run_num.name.isdigit() and (run_num / "pipeline.json").exists():
                        run_name = f"{concept_dir.name}/runs/{run_num.name}"
                        entry = _build_run_entry(
                            run_num,
                            f"/api/concept-assets/{concept_dir.name}/runs/{run_num.name}",
                            concept_slug=concept_dir.name,
                            cdn_prefix=f"concepts/{concept_dir.name}/runs/{run_num.name}",
                        )
                        entry["run_name"] = run_name
                        runs.append(entry)
            # 2b. Pipeline at concept root (legacy 5-stage flow)
            if (concept_dir / "pipeline.json").exists() and (concept_dir / "status.json").exists():
                entry = _build_run_entry(
                    concept_dir,
                    f"/api/concept-assets/{concept_dir.name}",
                    concept_slug=concept_dir.name,
                    cdn_prefix=f"concepts/{concept_dir.name}",
                )
                entry["run_name"] = concept_dir.name
                runs.append(entry)
            # 2c. run-* subdirectories (legacy flow)
            for sub in concept_dir.iterdir():
                if sub.is_dir() and sub.name.startswith("run") and (sub / "pipeline.json").exists():
                    run_name = f"{concept_dir.name}/{sub.name}"
                    entry = _build_run_entry(
                        sub,
                        f"/api/concept-assets/{concept_dir.name}/{sub.name}",
                        concept_slug=concept_dir.name,
                        cdn_prefix=f"concepts/{concept_dir.name}/{sub.name}",
                    )
                    entry["run_name"] = run_name
                    runs.append(entry)

    # Sort by modification time (most recent first)
    runs.sort(key=lambda r: r.get("started") or "", reverse=True)
    return runs


@app.get("/api/runs/{run_name:path}")
def get_run(run_name: str):
    """Full run details. Supports both 'run_name' and 'concept/run_name' paths."""
    return _get_run_summary(run_name)


ASSET_CACHE_HEADERS = {"Cache-Control": "public, max-age=86400, immutable"}


@app.get("/api/assets/{run_name}/{file_path:path}")
def serve_asset(run_name: str, file_path: str):
    """Serve an asset file (image, video, audio)."""
    full_path = RUNS_DIR / run_name / file_path
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")

    # Security: ensure path doesn't escape runs dir
    try:
        full_path.resolve().relative_to(RUNS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(full_path, headers=ASSET_CACHE_HEADERS)


@app.get("/api/concept-assets/{slug}/{subpath:path}")
def serve_concept_asset(slug: str, subpath: str):
    """Serve an asset file from a concept folder."""
    full_path = CONCEPTS_DIR / slug / subpath
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="Concept asset not found")

    try:
        full_path.resolve().relative_to(CONCEPTS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(full_path, headers=ASSET_CACHE_HEADERS)


@app.get("/api/concepts")
def list_concepts():
    """List all concept folders with basic metadata."""
    if not CONCEPTS_DIR.is_dir():
        return []

    concepts = []
    for d in sorted(CONCEPTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue

        has_plan = (d / "plan.md").exists()
        has_frames = (d / "frames").is_dir()
        frame_count = len(list((d / "frames").glob("*.png"))) + len(list((d / "frames").glob("*.jpg"))) if has_frames else 0

        # Find linked runs (new layout: runs/NNN/, legacy: run-*)
        linked_runs = []
        runs_sub = d / "runs"
        if runs_sub.is_dir():
            for run_num in sorted(runs_sub.iterdir()):
                if run_num.is_dir() and run_num.name.isdigit():
                    linked_runs.append(f"runs/{run_num.name}")
        for sub in d.iterdir():
            if sub.is_dir() and sub.name.startswith("run") and sub.name != "runs":
                linked_runs.append(sub.name)

            # Detect stage from files on disk
        stage = "intake"
        if (d / "director.json").exists():
            stage = "director"
        elif (d / "characters").is_dir():
            stage = "characters"
        elif (d / "creative.json").exists():
            stage = "creative"
        # Override from status.json if present
        status_file = d / "status.json"
        if status_file.exists():
            st = _read_json(status_file)
            if st and "stage" in st:
                stage = st["stage"]
        # If there are completed runs, mark as done/production
        has_completed_run = False
        has_any_run = len(linked_runs) > 0
        if has_any_run:
            for rp in linked_runs:
                rs = _read_json(d / rp / "status.json")
                if rs and rs.get("complete"):
                    has_completed_run = True
                    break
            if has_completed_run:
                stage = "done"
            elif stage == "director":
                stage = "production"

        # Extract title from creative.json if available
        title = None
        creative = _read_json(d / "creative.json")
        if creative:
            title = creative.get("title")

        concepts.append({
            "slug": d.name,
            "has_plan": has_plan,
            "frame_count": frame_count,
            "linked_runs": linked_runs,
            "stage": stage,
            "title": title,
        })

    return concepts


@app.get("/api/concepts/{slug}")
def get_concept(slug: str):
    """Full concept details with all linked runs and their shot assets for comparison."""
    concept = _get_concept_data(slug)
    if not concept:
        raise HTTPException(status_code=404, detail=f"Concept '{slug}' not found")

    concept_dir = CONCEPTS_DIR / slug

    # Gather all runs for this concept
    runs = []

    def _enrich_status_errors(status: dict) -> dict:
        """If top-level errors array is empty, build it from step-level failures."""
        if status.get("errors"):
            return status
        step_errors = []
        for step_id, step in status.get("steps", {}).items():
            if step.get("status") == "failed" and step.get("error"):
                step_errors.append({"step": step_id, "error": step["error"], "retries": step.get("retries")})
        if step_errors:
            status = {**status, "errors": step_errors}
        return status

    # Helper to build a run entry from a directory containing pipeline.json + status.json
    def _build_concept_run(run_dir: Path, run_name: str, label: str, asset_base: str, cdn_prefix: str):
        status = _read_json(run_dir / "status.json") or {}
        # Skip runs that were never executed (no status = no outputs)
        # But keep runs that are actively running (have started or have running steps)
        has_any_output = any(
            s.get("status") == "completed"
            for s in status.get("steps", {}).values()
        )
        is_running = status.get("started") or any(
            s.get("status") == "running"
            for s in status.get("steps", {}).values()
        )
        if not has_any_output and not status.get("complete") and not status.get("failed") and not is_running:
            return None
        pipeline = _read_json(run_dir / "pipeline.json") or {}
        spec = _read_json(run_dir / "production_spec.json")

        # Discover assets (with CDN resolution)
        assets = _resolve_assets(run_dir, asset_base, cdn_prefix)

        # Extract shot-level info: match video_gen nodes to their outputs
        shots = []
        for node in pipeline.get("nodes", []):
            node_id = node.get("id", "")
            if not (node_id.startswith("video_gen") or node_id.startswith("image_gen")):
                continue
            step_status = status.get("steps", {}).get(node_id, {})
            output_file = step_status.get("output", "").split("/")[-1] if step_status.get("output") else node.get("config", {}).get("output_filename")
            # Find the upscaled version too
            upscale_id = node_id.replace("video_gen", "upscale")
            upscale_step = status.get("steps", {}).get(upscale_id, {})
            upscale_file = upscale_step.get("output", "").split("/")[-1] if upscale_step.get("output") else None

            shot_data = {
                "node_id": node_id,
                "adapter": node.get("adapter", ""),
                "prompt": node.get("config", {}).get("prompt", ""),
                "status": step_status.get("status", "pending"),
                "duration_s": step_status.get("duration_s"),
                "output_url": assets.get(output_file) if output_file else None,
                "upscaled_url": assets.get(upscale_file) if upscale_file else None,
                "cost": None,
            }
            # Cost
            cost_info = status.get("cost", {})
            for b in cost_info.get("breakdown", []):
                if b.get("step") == node_id:
                    shot_data["cost"] = b.get("cost")
                    break

            shots.append(shot_data)

        thumb = None
        for candidate in ["final.mp4.thumb.png", "anchor_frame.png", "frame.png"]:
            if (run_dir / candidate).exists():
                thumb = f"{asset_base}/{candidate}"
                break

        # Cost: use actual from status.json, else estimate from pipeline
        actual_cost = status.get("cost", {}).get("total")
        estimated_cost = None
        if actual_cost is None and pipeline:
            try:
                from workflow.cost import estimate_pipeline_cost
                est = estimate_pipeline_cost(pipeline)
                estimated_cost = est.get("total")
            except Exception:
                pass

        return {
            "run_name": run_name,
            "label": label,
            "complete": status.get("complete", False),
            "failed": status.get("failed", False),
            "elapsed_s": status.get("elapsed_s"),
            "total_cost": actual_cost,
            "estimated_cost": estimated_cost,
            "shots": shots,
            "final_video": assets.get("final.mp4"),
            "thumbnail": thumb,
            "character_name": (spec or {}).get("character", {}).get("name"),
            "assets": assets,
            "pipeline": pipeline,
            "status": _enrich_status_errors(status),
        }

    # 1. Versioned runs in runs/NNN/ subfolders (new layout)
    runs_sub = concept_dir / "runs"
    if runs_sub.is_dir():
        for run_num in sorted(runs_sub.iterdir()):
            if run_num.is_dir() and run_num.name.isdigit() and (run_num / "pipeline.json").exists():
                entry = _build_concept_run(
                    run_num, f"{slug}/runs/{run_num.name}", f"Run {int(run_num.name)}",
                    f"/api/concept-assets/{slug}/runs/{run_num.name}",
                    f"concepts/{slug}/runs/{run_num.name}",
                )
                if entry:
                    runs.append(entry)

    # 2. Check concept root for pipeline.json (flat layout — may or may not have been executed)
    # Skip if we already found runs in runs/NNN/ — the root pipeline is just a staging copy
    if (concept_dir / "pipeline.json").exists() and not runs:
        has_status = (concept_dir / "status.json").exists()
        if has_status:
            entry = _build_concept_run(
                concept_dir, slug, "Pipeline",
                f"/api/concept-assets/{slug}", f"concepts/{slug}",
            )
            if entry:
                runs.append(entry)
        else:
            # Un-executed pipeline — show it with empty status so the UI can display it
            pipeline = _read_json(concept_dir / "pipeline.json") or {}
            estimated_cost = None
            try:
                from workflow.cost import estimate_pipeline_cost
                est = estimate_pipeline_cost(pipeline)
                estimated_cost = est.get("total")
            except Exception:
                pass
            shots = []
            for node in pipeline.get("nodes", []):
                node_id = node.get("id", "")
                if not (node_id.startswith("video_gen") or node_id.startswith("image_gen")):
                    continue
                shots.append({
                    "node_id": node_id,
                    "adapter": node.get("adapter", ""),
                    "prompt": node.get("config", {}).get("prompt", ""),
                    "status": "pending",
                    "duration_s": None,
                    "output_url": None,
                    "upscaled_url": None,
                    "cost": None,
                })
            runs.append({
                "run_name": slug,
                "label": "Pipeline",
                "complete": False,
                "failed": False,
                "elapsed_s": None,
                "total_cost": None,
                "estimated_cost": estimated_cost,
                "shots": shots,
                "final_video": None,
                "thumbnail": None,
                "character_name": None,
                "assets": {},
                "pipeline": pipeline,
                "status": {},
            })

    # 3. Check run-* subdirectories (legacy flow)
    for sub in sorted(concept_dir.iterdir()):
        if sub.is_dir() and sub.name.startswith("run") and (sub / "pipeline.json").exists():
            entry = _build_concept_run(
                sub, f"{slug}/{sub.name}", sub.name,
                f"/api/concept-assets/{slug}/{sub.name}",
                f"concepts/{slug}/{sub.name}",
            )
            if entry:
                runs.append(entry)

    concept["runs"] = runs
    return concept


class PromptUpdate(BaseModel):
    prompt: str


@app.patch("/api/runs/{run_name}/nodes/{node_id}")
def update_node_prompt(run_name: str, node_id: str, body: PromptUpdate):
    """Update a node's prompt in pipeline.json."""
    run_dir = RUNS_DIR / run_name
    pipeline_path = run_dir / "pipeline.json"

    if not pipeline_path.exists():
        raise HTTPException(status_code=404, detail="Pipeline not found")

    pipeline = _read_json(pipeline_path)
    node_found = False
    for node in pipeline.get("nodes", []):
        if node["id"] == node_id:
            node["config"]["prompt"] = body.prompt
            node_found = True
            break

    if not node_found:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")

    with open(pipeline_path, "w") as f:
        json.dump(pipeline, f, indent=2)

    # Also update the readable prompt file
    prompt_txt = run_dir / "prompts" / f"{node_id.replace('.', '_')}.txt"
    if prompt_txt.parent.exists():
        prompt_txt.write_text(body.prompt)

    return {"ok": True, "node_id": node_id}


class RerunRequest(BaseModel):
    step: str | None = None
    adapter: str | None = None


@app.post("/api/runs/{run_name:path}/rerun")
def rerun(run_name: str, body: RerunRequest):
    """Trigger a re-run of a specific step (or the whole pipeline).

    Before launching, versions existing output files so previous results
    are preserved as _v1, _v2, etc.
    """
    run_dir, _ = _resolve_run_dir(run_name)
    pipeline_path = run_dir / "pipeline.json"

    if not pipeline_path.exists():
        raise HTTPException(status_code=404, detail="Pipeline not found")

    pipeline = _read_json(pipeline_path) or {}
    status = _read_json(run_dir / "status.json") or {}

    # Version existing outputs before overwriting
    versioned_files: list[str] = []
    if body.step:
        # Single step rerun — version just that step's outputs
        versioned_files = _version_step_outputs(run_dir, body.step, pipeline, status)
    else:
        # Full pipeline rerun — version all step outputs
        for node in pipeline.get("nodes", []):
            versioned_files.extend(
                _version_step_outputs(run_dir, node["id"], pipeline, status)
            )

    # Build engine command
    cmd = [
        sys.executable, "-m", "workflow.engine",
        "--pipeline", str(pipeline_path),
    ]

    # For step-level reruns with the spec path, use --retry
    spec_path = run_dir / "production_spec.json"
    status_path = run_dir / "status.json"
    if body.step and spec_path.exists() and status_path.exists():
        cmd = [
            sys.executable, "-m", "workflow.engine",
            "--spec", str(spec_path),
            "--retry", str(status_path),
            "--step", body.step,
        ]
        if body.adapter:
            cmd.extend(["--adapter", body.adapter])

    # Run in background
    process = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    return {
        "ok": True,
        "pid": process.pid,
        "run_name": run_name,
        "step": body.step,
        "versioned": versioned_files,
        "message": f"Re-run started (PID {process.pid})",
    }


class RegenerateShotRequest(BaseModel):
    node_id: str  # e.g. "video_gen.shot_01"
    prompt: str | None = None  # new prompt (None = keep existing)
    adapter: str | None = None  # override adapter (None = keep existing)
    source_run: str  # run label like "Run 1" to copy from


@app.post("/api/concepts/{slug}/regenerate-shot")
def regenerate_shot(slug: str, body: RegenerateShotRequest):
    """Regenerate a single shot by copying a run and re-running the target node.

    1. Copies the source run folder → next runs/NNN/
    2. Updates the pipeline.json prompt for the target node (if new prompt given)
    3. Launches engine with --retry + --step to only re-run that node + dependents
    """
    import shutil

    concept_dir = CONCEPTS_DIR / slug
    if not concept_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Concept '{slug}' not found")

    # Find source run directory from label (e.g. "Run 1" → runs/001/)
    runs_dir = concept_dir / "runs"
    source_dir: Path | None = None
    if runs_dir.is_dir():
        for sub in sorted(runs_dir.iterdir()):
            if sub.is_dir() and sub.name.isdigit():
                label = f"Run {int(sub.name)}"
                if label == body.source_run:
                    source_dir = sub
                    break

    if not source_dir or not (source_dir / "pipeline.json").exists():
        raise HTTPException(status_code=404, detail=f"Source run '{body.source_run}' not found")
    if not (source_dir / "status.json").exists():
        raise HTTPException(status_code=400, detail="Source run has no status.json")

    # Verify the node exists in the pipeline
    pipeline = _read_json(source_dir / "pipeline.json") or {}
    target_node = None
    for node in pipeline.get("nodes", []):
        if node.get("id") == body.node_id:
            target_node = node
            break
    if not target_node:
        raise HTTPException(status_code=404, detail=f"Node '{body.node_id}' not found in pipeline")

    # Create new run by copying the source
    existing = []
    for name in runs_dir.iterdir():
        if name.is_dir() and name.name.isdigit():
            existing.append(int(name.name))
    next_num = max(existing) + 1 if existing else 1
    new_run_dir = runs_dir / f"{next_num:03d}"
    shutil.copytree(source_dir, new_run_dir)

    # Update the prompt in the new pipeline.json if a new prompt was given
    new_pipeline_path = new_run_dir / "pipeline.json"
    if body.prompt is not None:
        new_pipeline = _read_json(new_pipeline_path) or {}
        for node in new_pipeline.get("nodes", []):
            if node.get("id") == body.node_id:
                node.setdefault("config", {})["prompt"] = body.prompt
                break
        new_pipeline_path.write_text(json.dumps(new_pipeline, indent=2))

    # Update adapter if overridden
    if body.adapter is not None:
        new_pipeline = _read_json(new_pipeline_path) or {}
        for node in new_pipeline.get("nodes", []):
            if node.get("id") == body.node_id:
                node["adapter"] = body.adapter
                break
        new_pipeline_path.write_text(json.dumps(new_pipeline, indent=2))

    # Build engine command: --retry on the copied status + --step for targeted re-run
    # We need to use the spec path. The engine's --retry + --step re-runs only
    # the target node + dependents, keeping completed outputs from the copy.
    spec_path = new_run_dir / "production_spec.json"
    status_path = new_run_dir / "status.json"

    # Reset the target step + dependents in the copied status.json
    new_status = _read_json(status_path) or {}
    steps = new_status.get("steps", {})

    # Find all dependents of the target node (transitively)
    deps_to_reset = {body.node_id}
    changed = True
    new_pipeline_data = _read_json(new_pipeline_path) or {}
    while changed:
        changed = False
        for node in new_pipeline_data.get("nodes", []):
            nid = node.get("id", "")
            if nid in deps_to_reset:
                continue
            if any(d in deps_to_reset for d in node.get("depends_on", [])):
                deps_to_reset.add(nid)
                changed = True

    # Reset target + dependents to pending, delete their output files
    for step_id in deps_to_reset:
        if step_id in steps:
            old_output = steps[step_id].get("output")
            if old_output:
                old_path = Path(old_output)
                if not old_path.is_absolute():
                    old_path = new_run_dir / old_path
                if old_path.exists():
                    old_path.unlink()
            steps[step_id]["status"] = "pending"
            steps[step_id].pop("output", None)
            steps[step_id].pop("error", None)
            steps[step_id].pop("duration_s", None)

    # Mark run as incomplete
    new_status["complete"] = False
    new_status["failed"] = False
    status_path.write_text(json.dumps(new_status, indent=2))

    # Set output_dir in pipeline to the new run dir (so engine writes there)
    new_pipeline_data["output_dir"] = str(new_run_dir)
    new_pipeline_path.write_text(json.dumps(new_pipeline_data, indent=2))

    # Use --pipeline --retry to resume from the prepared status
    cmd = [
        sys.executable, "-m", "workflow.engine",
        "--pipeline", str(new_pipeline_path),
        "--retry", str(status_path),
    ]

    # Launch in background
    env = _claude_env()
    process = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    new_label = f"Run {next_num}"
    return {
        "ok": True,
        "pid": process.pid,
        "new_run": new_label,
        "new_run_dir": str(new_run_dir),
        "node_id": body.node_id,
        "dependents_reset": list(deps_to_reset - {body.node_id}),
        "message": f"Regenerating {body.node_id} → {new_label} (PID {process.pid})",
    }


@app.post("/api/runs/{run_name:path}/cdn-sync")
def cdn_sync(run_name: str):
    """Trigger CDN upload for all assets in a run. Returns immediately — uploads happen in background."""
    if not CDN_ENABLED:
        return {"ok": False, "message": "CDN not configured (missing SUPABASE_URL/SUPABASE_SECRET_KEY)"}

    run_dir, asset_base = _resolve_run_dir(run_name)
    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Run '{run_name}' not found")

    cdn_prefix = f"runs/{run_name}" if not run_name.startswith("concepts/") else run_name
    queued = 0
    cache = _read_cdn_cache(run_dir)

    for f in run_dir.iterdir():
        if f.suffix in (".png", ".jpg", ".jpeg", ".mp4", ".mp3", ".webm"):
            if f.name not in cache:
                local_url = f"{asset_base}/{f.name}"
                _resolve_asset_url(run_dir, f.name, local_url, cdn_prefix)
                queued += 1

    return {"ok": True, "queued": queued, "already_cached": len(cache)}


@app.get("/api/runs/{run_name:path}/status")
def poll_status(run_name: str):
    """Poll current run status (for live updates)."""
    run_dir, _ = _resolve_run_dir(run_name)
    status = _read_json(run_dir / "status.json")
    if not status:
        raise HTTPException(status_code=404, detail="Status not found")
    return status


# ---------------------------------------------------------------------------
# Plan CRUD — structured plan.json endpoints
# ---------------------------------------------------------------------------

class PlanCreate(BaseModel):
    brief: str
    profile: str = "cheap"
    aspect_ratio: str = "9:16"


class PlanShotUpdate(BaseModel):
    """Partial update for a single shot in the plan."""
    name: str | None = None
    type: str | None = None
    duration: float | None = None
    direction: str | None = None
    setting: str | None = None
    camera: str | None = None
    lighting: str | None = None
    dialogue: str | None = None
    voiceover: str | None = None
    text_overlay: str | None = None
    audio: str | None = None
    frame_source: str | None = None
    frame_source_ref: str | None = None
    selected_model: str | None = None
    status: str | None = None


class PlanUpdate(BaseModel):
    """Partial update for the plan itself."""
    title: str | None = None
    angle: str | None = None
    profile: str | None = None
    aspect_ratio: str | None = None
    status: str | None = None
    compliance_notes: str | None = None


@app.get("/api/plans/{slug}")
def get_plan(slug: str):
    """Get the structured plan for a concept."""
    concept_dir = CONCEPTS_DIR / slug
    plan_path = concept_dir / "plan.json"

    if not plan_path.exists():
        # Fall back: if plan.md exists but no plan.json, return null plan_json
        plan_md = concept_dir / "plan.md"
        if plan_md.exists():
            return {"slug": slug, "plan_json": None, "plan_md": plan_md.read_text()}
        raise HTTPException(status_code=404, detail=f"No plan found for concept '{slug}'")

    return {"slug": slug, "plan_json": _read_json(plan_path)}


@app.put("/api/plans/{slug}")
def save_plan(slug: str, body: dict):
    """Save a full plan.json for a concept (create or overwrite)."""
    concept_dir = CONCEPTS_DIR / slug
    concept_dir.mkdir(parents=True, exist_ok=True)

    plan_path = concept_dir / "plan.json"
    with open(plan_path, "w") as f:
        json.dump(body, f, indent=2, ensure_ascii=False)

    # Also render plan.md from the structured data
    try:
        from workflow.plan_schema import Plan as PlanSchema
        plan_obj = PlanSchema.from_dict(body)
        md_path = concept_dir / "plan.md"
        md_path.write_text(plan_obj.to_markdown())
    except Exception:
        pass  # Non-critical — plan.json is the source of truth

    return {"ok": True, "slug": slug}


@app.patch("/api/plans/{slug}")
def update_plan(slug: str, body: PlanUpdate):
    """Partially update plan-level fields (title, angle, profile, status, etc.)."""
    plan_path = CONCEPTS_DIR / slug / "plan.json"
    if not plan_path.exists():
        raise HTTPException(status_code=404, detail="Plan not found")

    plan = _read_json(plan_path)
    updates = body.model_dump(exclude_none=True)
    plan.update(updates)

    with open(plan_path, "w") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)

    return {"ok": True, "slug": slug, "updated": list(updates.keys())}


@app.patch("/api/plans/{slug}/shots/{shot_index}")
def update_shot(slug: str, shot_index: int, body: PlanShotUpdate):
    """Update a single shot in the plan by index."""
    plan_path = CONCEPTS_DIR / slug / "plan.json"
    if not plan_path.exists():
        raise HTTPException(status_code=404, detail="Plan not found")

    plan = _read_json(plan_path)
    shots = plan.get("shots", [])
    if shot_index < 0 or shot_index >= len(shots):
        raise HTTPException(status_code=404, detail=f"Shot index {shot_index} out of range")

    updates = body.model_dump(exclude_none=True)
    shots[shot_index].update(updates)

    with open(plan_path, "w") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)

    return {"ok": True, "slug": slug, "shot_index": shot_index, "updated": list(updates.keys())}


@app.post("/api/plans/{slug}/shots/{shot_index}/optimize")
def optimize_shot_prompt(slug: str, shot_index: int, body: dict):
    """Generate a model-specific prompt for a shot using Claude Code CLI.

    Body: {"model": "kling_v3"} — the target model to optimize for.
    Spawns Claude Code with the appropriate prompting skill to generate
    the optimized prompt, then writes it back into plan.json.
    """
    plan_path = CONCEPTS_DIR / slug / "plan.json"
    if not plan_path.exists():
        raise HTTPException(status_code=404, detail="Plan not found")

    plan = _read_json(plan_path)
    shots = plan.get("shots", [])
    if shot_index < 0 or shot_index >= len(shots):
        raise HTTPException(status_code=404, detail=f"Shot index {shot_index} out of range")

    model = body.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="Missing 'model' field")

    shot = shots[shot_index]
    direction = shot.get("direction", "")
    shot_type = shot.get("type", "B-ROLL")
    dialogue = shot.get("dialogue", "")
    setting = shot.get("setting", "")
    camera = shot.get("camera", "")
    lighting = shot.get("lighting", "")
    duration = shot.get("duration", 8)

    # Build the prompt for Claude Code
    creative_brief = (
        f"Shot: \"{shot.get('name', 'Untitled')}\"\n"
        f"Type: {shot_type}\n"
        f"Duration: {duration}s\n"
        f"Direction: {direction}\n"
    )
    if setting:
        creative_brief += f"Setting: {setting}\n"
    if camera:
        creative_brief += f"Camera: {camera}\n"
    if lighting:
        creative_brief += f"Lighting: {lighting}\n"
    if dialogue:
        creative_brief += f"Dialogue: {dialogue}\n"

    # Map model to prompting skill
    skill_map = {
        "kling_v3": "kling-prompting",
        "veo_v3": "veo-prompting",
        "sora_v2": "sora-prompting",
        "kling_v2": "veo-prompting",  # Kling v2 uses Veo 5-part format
        "seedance_v1_5": "veo-prompting",
        "hailuo_02": "veo-prompting",
    }
    skill = skill_map.get(model, "veo-prompting")

    # Spawn Claude Code CLI to generate the optimized prompt
    claude_prompt = (
        f"Use the /{skill} skill to write a production-ready video prompt for this shot. "
        f"Output ONLY the final prompt text, nothing else.\n\n{creative_brief}"
    )

    cmd = [
        "claude", "--print", "--dangerously-skip-permissions",
        "-p", claude_prompt,
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            env=_claude_env(),
            timeout=120,
        )
        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Claude Code failed: {result.stderr[:500]}"
            )
        optimized_prompt = result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Claude Code timed out")
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail="Claude Code CLI not found. Install with: npm install -g @anthropic-ai/claude-code"
        )

    # Write the optimized prompt back into plan.json
    if "prompts" not in shot:
        shot["prompts"] = {}
    shot["prompts"][model] = optimized_prompt

    with open(plan_path, "w") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)

    return {
        "ok": True,
        "slug": slug,
        "shot_index": shot_index,
        "model": model,
        "prompt": optimized_prompt,
    }


# ---------------------------------------------------------------------------
# Stage-based concept CRUD (creative.json / director.json / status.json)
# ---------------------------------------------------------------------------

ConceptStage = Literal[
    "intake", "creative", "characters", "director",
    "production", "review", "done",
]


class StageAdvance(BaseModel):
    to_stage: str


def _read_concept_status(slug: str) -> dict:
    """Read or synthesize status.json for a concept."""
    status_path = CONCEPTS_DIR / slug / "status.json"
    if status_path.exists():
        return _read_json(status_path) or {"stage": "intake"}
    # Synthesize stage from files on disk
    concept_dir = CONCEPTS_DIR / slug
    if (concept_dir / "director.json").exists():
        return {"stage": "director"}
    if (concept_dir / "characters").is_dir():
        return {"stage": "characters"}
    if (concept_dir / "creative.json").exists():
        return {"stage": "creative"}
    return {"stage": "intake"}


def _write_concept_status(slug: str, status: dict) -> None:
    path = CONCEPTS_DIR / slug / "status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(status, f, indent=2)


@app.get("/api/concepts/{slug}/creative")
def get_creative(slug: str):
    """Get the creative document (story, characters, beats)."""
    creative_path = CONCEPTS_DIR / slug / "creative.json"
    if not creative_path.exists():
        raise HTTPException(status_code=404, detail="Creative not found")
    data = _read_json(creative_path)
    # Also return rendered markdown
    try:
        from workflow.creative_schema import Creative as CreativeSchema
        obj = CreativeSchema.from_dict(data)
        return {"slug": slug, "creative": data, "creative_md": obj.to_markdown()}
    except Exception:
        return {"slug": slug, "creative": data, "creative_md": None}


@app.put("/api/concepts/{slug}/creative")
def save_creative(slug: str, body: dict):
    """Save creative.json (create or overwrite)."""
    concept_dir = CONCEPTS_DIR / slug
    concept_dir.mkdir(parents=True, exist_ok=True)
    creative_path = concept_dir / "creative.json"
    with open(creative_path, "w") as f:
        json.dump(body, f, indent=2, ensure_ascii=False)
    # Render markdown
    try:
        from workflow.creative_schema import Creative as CreativeSchema
        obj = CreativeSchema.from_dict(body)
        (concept_dir / "creative.md").write_text(obj.to_markdown())
    except Exception:
        pass
    return {"ok": True, "slug": slug}


@app.get("/api/concepts/{slug}/director")
def get_director(slug: str):
    """Get the director document (production specs per shot)."""
    director_path = CONCEPTS_DIR / slug / "director.json"
    if not director_path.exists():
        raise HTTPException(status_code=404, detail="Director not found")
    data = _read_json(director_path)
    try:
        from workflow.director_schema import DirectorPlan as DirectorSchema
        obj = DirectorSchema.from_dict(data)
        return {"slug": slug, "director": data, "director_md": obj.to_markdown()}
    except Exception:
        return {"slug": slug, "director": data, "director_md": None}


@app.put("/api/concepts/{slug}/director")
def save_director(slug: str, body: dict):
    """Save director.json (create or overwrite)."""
    concept_dir = CONCEPTS_DIR / slug
    concept_dir.mkdir(parents=True, exist_ok=True)
    director_path = concept_dir / "director.json"
    with open(director_path, "w") as f:
        json.dump(body, f, indent=2, ensure_ascii=False)
    try:
        from workflow.director_schema import DirectorPlan as DirectorSchema
        obj = DirectorSchema.from_dict(body)
        (concept_dir / "director.md").write_text(obj.to_markdown())
    except Exception:
        pass
    return {"ok": True, "slug": slug}


@app.get("/api/concepts/{slug}/status")
def get_concept_status(slug: str):
    """Get the current pipeline stage for a concept."""
    if not (CONCEPTS_DIR / slug).is_dir():
        raise HTTPException(status_code=404, detail="Concept not found")
    return _read_concept_status(slug)


@app.post("/api/concepts/{slug}/advance")
def advance_concept(slug: str, body: StageAdvance):
    """Advance a concept to the next pipeline stage."""
    if not (CONCEPTS_DIR / slug).is_dir():
        raise HTTPException(status_code=404, detail="Concept not found")
    status = _read_concept_status(slug)
    status["stage"] = body.to_stage
    _write_concept_status(slug, status)
    return {"ok": True, "slug": slug, "stage": body.to_stage}


# ---------------------------------------------------------------------------
# Character generation endpoints
# ---------------------------------------------------------------------------

@app.get("/api/concepts/{slug}/characters")
def list_characters(slug: str):
    """List all characters with their reference images."""
    chars_dir = CONCEPTS_DIR / slug / "characters"
    if not chars_dir.is_dir():
        return []
    result = []
    for d in sorted(chars_dir.iterdir()):
        if not d.is_dir():
            continue
        options = []
        selected_url = None
        cdn_prefix = f"concepts/{slug}/characters/{d.name}"
        for f in sorted(d.iterdir()):
            if f.suffix in (".png", ".jpg", ".jpeg"):
                local_url = f"/api/concept-assets/{slug}/characters/{d.name}/{f.name}"
                url = _resolve_asset_url(d, f.name, local_url, cdn_prefix) if CDN_ENABLED else local_url
                options.append({"name": f.name, "url": url})
                if f.name == "selected.png":
                    selected_url = url
        result.append({
            "name": d.name,
            "options": options,
            "selected_url": selected_url,
        })
    return result


@app.post("/api/concepts/{slug}/characters/{name}/select")
def select_character(slug: str, name: str, body: dict):
    """Select a character reference image by filename."""
    chars_dir = CONCEPTS_DIR / slug / "characters" / name
    if not chars_dir.is_dir():
        raise HTTPException(status_code=404, detail="Character not found")
    source = body.get("filename")
    if not source:
        raise HTTPException(status_code=400, detail="Missing 'filename'")
    source_path = chars_dir / source
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    import shutil
    shutil.copy2(source_path, chars_dir / "selected.png")
    return {"ok": True, "name": name}


# ---------------------------------------------------------------------------
# Per-shot version management
# ---------------------------------------------------------------------------

@app.get("/api/concepts/{slug}/shots/{shot_id}/versions")
def list_shot_versions(slug: str, shot_id: str):
    """List all versions of a shot (frames + clips)."""
    shot_dir = CONCEPTS_DIR / slug / "shots" / shot_id / "versions"
    if not shot_dir.is_dir():
        return []
    versions = []
    cdn_prefix = f"concepts/{slug}/shots/{shot_id}/versions"
    for v_dir in sorted(shot_dir.iterdir()):
        if not v_dir.is_dir() or not v_dir.name.startswith("v"):
            continue
        version_num = int(v_dir.name[1:])
        entry: dict[str, Any] = {"version": version_num}
        for f in v_dir.iterdir():
            local_url = f"/api/concept-assets/{slug}/shots/{shot_id}/versions/{v_dir.name}/{f.name}"
            url = _resolve_asset_url(v_dir, f.name, local_url, f"{cdn_prefix}/{v_dir.name}") if CDN_ENABLED else local_url
            if f.suffix in (".mp4", ".webm"):
                if "upscaled" in f.stem:
                    entry["clip_upscaled_url"] = url
                else:
                    entry["clip_url"] = url
            elif f.suffix in (".png", ".jpg"):
                entry["frame_url"] = url
            elif f.name == "meta.json":
                entry["meta"] = _read_json(f) or {}
        # Read prompt from shot-level prompts dir
        prompt_dir = CONCEPTS_DIR / slug / "shots" / shot_id / "prompts"
        selected_model_path = CONCEPTS_DIR / slug / "shots" / shot_id / "selected_model.txt"
        if selected_model_path.exists():
            model = selected_model_path.read_text().strip()
            prompt_file = prompt_dir / f"{model.replace('fal_', '').replace('_flf', '')}.txt"
            if prompt_file.exists():
                entry["prompt"] = prompt_file.read_text()
        entry["created_at"] = v_dir.stat().st_mtime
        versions.append(entry)
    return versions


@app.post("/api/concepts/{slug}/shots/{shot_id}/select-version")
def select_shot_version(slug: str, shot_id: str, body: dict):
    """Select which version of a shot to use."""
    version = body.get("version")
    if version is None:
        raise HTTPException(status_code=400, detail="Missing 'version'")
    selected_path = CONCEPTS_DIR / slug / "shots" / shot_id / "selected_version"
    selected_path.write_text(f"v{version}")
    return {"ok": True, "shot_id": shot_id, "version": version}


@app.get("/api/concepts/{slug}/shots/{shot_id}/prompt-diff")
def get_prompt_diff(slug: str, shot_id: str, v1: int = 1, v2: int = 2):
    """Compare prompts between two versions of a shot."""
    import difflib
    prompt_dir = CONCEPTS_DIR / slug / "shots" / shot_id / "prompts"
    # Try to find prompts — look at meta.json in each version for the prompt used
    v1_prompt = ""
    v2_prompt = ""
    versions_dir = CONCEPTS_DIR / slug / "shots" / shot_id / "versions"
    for v_num, target in [(v1, "v1_prompt"), (v2, "v2_prompt")]:
        v_dir = versions_dir / f"v{v_num}"
        meta = _read_json(v_dir / "meta.json") if v_dir.is_dir() else None
        if meta and "prompt" in meta:
            if target == "v1_prompt":
                v1_prompt = meta["prompt"]
            else:
                v2_prompt = meta["prompt"]
    # Fall back to current prompt files
    if not v1_prompt and prompt_dir.is_dir():
        for f in prompt_dir.iterdir():
            if f.suffix == ".txt":
                v1_prompt = f.read_text()
                break
    diff = list(difflib.unified_diff(
        v1_prompt.splitlines(), v2_prompt.splitlines(),
        fromfile=f"v{v1}", tofile=f"v{v2}", lineterm=""
    ))
    diff_lines = []
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            diff_lines.append({"type": "add", "text": line[1:]})
        elif line.startswith("-") and not line.startswith("---"):
            diff_lines.append({"type": "remove", "text": line[1:]})
        elif not line.startswith("@@") and not line.startswith("---") and not line.startswith("+++"):
            diff_lines.append({"type": "same", "text": line.lstrip(" ")})
    return {"v1_prompt": v1_prompt, "v2_prompt": v2_prompt, "diff_lines": diff_lines}


@app.post("/api/concepts/{slug}/shots/{shot_id}/approve")
def approve_shot(slug: str, shot_id: str):
    """Mark a shot as approved."""
    status = _read_concept_status(slug)
    if "shots" not in status:
        status["shots"] = {}
    status["shots"][shot_id] = {"approved": True}
    _write_concept_status(slug, status)
    return {"ok": True, "shot_id": shot_id}


@app.patch("/api/concepts/{slug}/shots/{shot_id}/spec")
def update_shot_spec(slug: str, shot_id: str, body: dict):
    """Update a shot's director spec."""
    spec_path = CONCEPTS_DIR / slug / "shots" / shot_id / "spec.json"
    if not spec_path.exists():
        # Try to extract from director.json
        director_path = CONCEPTS_DIR / slug / "director.json"
        if not director_path.exists():
            raise HTTPException(status_code=404, detail="Shot spec not found")
        director = _read_json(director_path)
        for shot in director.get("shots", []):
            if shot.get("shot_id") == shot_id:
                # Create the shot dir and spec
                shot_dir = CONCEPTS_DIR / slug / "shots" / shot_id
                shot_dir.mkdir(parents=True, exist_ok=True)
                spec_path = shot_dir / "spec.json"
                shot.update(body)
                with open(spec_path, "w") as f:
                    json.dump(shot, f, indent=2, ensure_ascii=False)
                return {"ok": True, "shot_id": shot_id}
        raise HTTPException(status_code=404, detail=f"Shot '{shot_id}' not in director.json")

    spec = _read_json(spec_path)
    spec.update(body)
    with open(spec_path, "w") as f:
        json.dump(spec, f, indent=2, ensure_ascii=False)
    return {"ok": True, "shot_id": shot_id}


# ---------------------------------------------------------------------------
# Concept progress (aggregated shot-level view for production screen)
# ---------------------------------------------------------------------------

@app.get("/api/concepts/{slug}/progress")
def get_concept_progress(slug: str):
    """Get aggregated shot-level progress for the production screen."""
    concept_dir = CONCEPTS_DIR / slug
    if not concept_dir.is_dir():
        raise HTTPException(status_code=404, detail="Concept not found")

    status = _read_concept_status(slug)
    director = _read_json(concept_dir / "director.json")

    # Map pipeline nodes to shots
    pipeline = _read_json(concept_dir / "pipeline.json")
    run_status = None

    # Check concept-embedded runs for status
    for sub in sorted(concept_dir.iterdir(), reverse=True):
        if sub.is_dir() and sub.name.startswith("run") and (sub / "status.json").exists():
            run_status = _read_json(sub / "status.json")
            if not pipeline:
                pipeline = _read_json(sub / "pipeline.json")
            break

    shots_progress = []
    if director:
        for shot in director.get("shots", []):
            shot_id = shot.get("shot_id", "")
            beat_name = shot.get("beat_name", shot_id)
            progress: dict[str, Any] = {
                "name": beat_name,
                "shot_id": shot_id,
                "stage": "pending",
                "progress_pct": 0,
                "thumbnail_url": None,
                "cost": 0.0,
            }

            if run_status:
                steps = run_status.get("steps", {})
                # Find matching pipeline nodes for this shot
                video_step = steps.get(f"video_gen.{shot_id}", {})
                upscale_step = steps.get(f"upscale.{shot_id}", {})

                if upscale_step.get("status") == "completed":
                    progress["stage"] = "complete"
                    progress["progress_pct"] = 100
                elif video_step.get("status") == "completed":
                    progress["stage"] = "upscale"
                    progress["progress_pct"] = 75
                elif video_step.get("status") == "running":
                    progress["stage"] = "video"
                    progress["progress_pct"] = 40
                elif video_step.get("status") == "failed":
                    progress["stage"] = "failed"
                    progress["error"] = video_step.get("error")

                # Cost
                for b in run_status.get("cost", {}).get("breakdown", []):
                    if shot_id in b.get("step", ""):
                        progress["cost"] += b.get("cost", 0)

                # Thumbnail
                frame_path = concept_dir / "shots" / shot_id / "frame" / "anchor.png"
                if frame_path.exists():
                    progress["thumbnail_url"] = f"/api/concept-assets/{slug}/shots/{shot_id}/frame/anchor.png"

            shots_progress.append(progress)

    total_cost = sum(s.get("cost", 0) for s in shots_progress)
    elapsed = run_status.get("elapsed_s", 0) if run_status else 0

    return {
        "stage": status.get("stage", "intake"),
        "shots": shots_progress,
        "total_cost": total_cost,
        "elapsed_s": elapsed,
    }


# ---------------------------------------------------------------------------
# Project creation
# ---------------------------------------------------------------------------

class ProjectCreate(BaseModel):
    source_url: str | None = None
    brief: str | None = None
    notes: str | None = None


@app.post("/api/projects/create")
def create_project(body: ProjectCreate):
    """Create a new project — returns a slug immediately, generation runs async."""
    import time

    if not body.source_url and not body.brief:
        raise HTTPException(status_code=400, detail="Provide source_url or brief")

    # Generate slug
    source = body.brief or body.source_url or "untitled"
    slug_base = re.sub(r"[^a-z0-9]+", "-", source[:40].lower()).strip("-")
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    slug = f"{slug_base}-{timestamp}"

    concept_dir = CONCEPTS_DIR / slug
    concept_dir.mkdir(parents=True, exist_ok=True)

    # Write initial status
    _write_concept_status(slug, {"stage": "intake"})

    # Write concept.json
    concept_meta = {
        "slug": slug,
        "source_url": body.source_url,
        "brief": body.brief,
        "notes": body.notes,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(concept_dir / "concept.json", "w") as f:
        json.dump(concept_meta, f, indent=2)

    return {"ok": True, "slug": slug, "stage": "intake"}


# ---------------------------------------------------------------------------
# Plan CRUD — structured plan.json endpoints (legacy, preserved for compat)
# ---------------------------------------------------------------------------

@app.post("/api/plans/generate")
def generate_plan(body: PlanCreate):
    """Generate a structured plan from a brief using Claude Code CLI.

    Spawns Claude Code with the scout-concept skill context to produce
    a plan.json, then saves it to the concept folder.
    """
    import time

    # Generate slug from brief
    slug_base = re.sub(r"[^a-z0-9]+", "-", body.brief[:40].lower()).strip("-")
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    slug = f"{slug_base}-{timestamp}"

    concept_dir = CONCEPTS_DIR / slug
    concept_dir.mkdir(parents=True, exist_ok=True)

    # Spawn Claude Code to generate the plan
    claude_prompt = (
        f"Generate a structured production plan for the following brief. "
        f"Output ONLY valid JSON matching the Plan schema from workflow/plan_schema.py. "
        f"Profile: {body.profile}. Aspect ratio: {body.aspect_ratio}. "
        f"Set the slug to \"{slug}\". "
        f"Include 3-5 shots with creative beat names, mixed shot types "
        f"(TALKING_HEAD, B-ROLL, PRODUCT as appropriate), directions, "
        f"settings, camera, lighting, and dialogue/voiceover. "
        f"Include a character with full details. "
        f"Brief: {body.brief}"
    )

    cmd = [
        "claude", "--print", "--dangerously-skip-permissions",
        "-p", claude_prompt,
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            env=_claude_env(),
            timeout=180,
        )
        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Claude Code failed: {result.stderr[:500]}"
            )

        # Extract JSON from response (may have markdown fences)
        output = result.stdout.strip()
        # Strip markdown code fences if present
        if "```json" in output:
            output = output.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in output:
            output = output.split("```", 1)[1].split("```", 1)[0].strip()

        plan_data = json.loads(output)

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Plan generation timed out")
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail="Claude Code CLI not found"
        )
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Claude Code returned invalid JSON: {str(e)}"
        )

    # Save plan.json
    plan_path = concept_dir / "plan.json"
    with open(plan_path, "w") as f:
        json.dump(plan_data, f, indent=2, ensure_ascii=False)

    # Render plan.md
    try:
        from workflow.plan_schema import Plan as PlanSchema
        plan_obj = PlanSchema.from_dict(plan_data)
        (concept_dir / "plan.md").write_text(plan_obj.to_markdown())
    except Exception:
        pass

    return {
        "ok": True,
        "slug": slug,
        "plan": plan_data,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8420, reload=True)
