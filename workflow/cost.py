"""Cost estimation for production specs.

Estimates the total cost of a production run based on the adapters used
and the number of steps that will be created. Uses model_profiles to
resolve adapter defaults — never hardcodes adapter names.
"""

from workflow.model_profiles import resolve_adapter

# Cost per invocation at default duration for each adapter (USD).
# Default durations: Kling 10s, Veo 8s, Sora 8s, Seedance 8s, LTX 8s, Hailuo 10s.
# NOTE: Per-shot duration overrides are not accounted for — costs are flat per invocation.
# A shot with duration=5 and duration=10 on the same adapter will show the same cost.
COST_PER_STEP = {
    "fal_nano_banana_v2": 0.05,      # per image
    "fal_nano_banana_edit": 0.15,    # per edit (4K = $0.30)
    "fal_nano_banana_scene_transfer": 0.08,  # Gemini (~free) + Nano Banana Pro ($0.08)
    "fal_dreamina_v3": 0.03,         # per image
    "fal_kling_v2": 0.70,            # 10s default (~$0.07/sec)
    "fal_kling_v3": 1.00,            # 10s default (~$0.10/sec). Face locking: black start frame + character_ref_frame_path
    "fal_kling_v3_ref": 1.00,        # deprecated — use fal_kling_v3 with black start frame + elements
    "fal_veo_v3_flf": 1.20,          # 8s default with audio ($0.15/sec, fast tier, image-to-video)
    "fal_sora_v2": 4.00,             # 8s default (~$0.50/sec)
    "fal_sora_v2_t2v": 4.00,         # 8s default (~$0.50/sec), text-to-video
    "openai_sora_character": 0.00,   # included in Sora usage
    "openai_sora_t2v": 0.80,        # sora-2 @ 720p, 8s default ($0.10/sec). Pro: $2.40-$4.00
    "openai_sora_i2v": 0.80,        # sora-2 @ 720p, 8s default ($0.10/sec). Pro: $2.40-$4.00
    "fal_veo_v3_t2v": 1.20,          # 8s default with audio ($0.15/sec), text-to-video
    "fal_kling_v3_t2v": 1.00,        # 10s default (~$0.10/sec), text-to-video
    "fal_seedance_v1_5": 0.42,       # 8s default at 720p with audio
    "fal_ltx_v2": 0.48,              # 8s default at 1080p ($0.06/sec)
    "fal_hailuo_02": 0.45,           # 10s default at 768p ($0.045/sec)
    "elevenlabs_tts": 0.15,          # per narration
    "elevenlabs_voice_design": 0.15, # per voice design
    "elevenlabs_music": 0.10,        # per track
    "fal_topaz_upscale": 0.10,       # ~$0.02/s for 5s clip at 1080p
    "fal_topaz_image_upscale": 0.04,  # per image (2x upscale)
    "freepik_magnific_upscale": 0.15, # ~€0.10-0.20 per 2x upscale of 2K portrait
    "local_ffmpeg": 0.00,            # free (local)
    "ffmpeg_concat": 0.00,           # free (local)
    "ffmpeg_mix_audio": 0.00,        # free (local)
    "ffmpeg_extract_last_frame": 0.00,  # free (local)
    "ffmpeg_extract_first_frame": 0.00, # free (local)
    "pil_render": 0.00,              # free (local)
    "browser_sora": 0.00,            # free (uses ChatGPT Plus/Pro subscription credits)
}


def estimate_cost(spec: dict) -> dict:
    """Estimate cost from a production spec.

    Uses the same resolve_adapter() logic as the templates so the cost
    estimate always matches the actual adapters that will run.
    """
    models = spec.get("models", {})
    video_type = spec.get("video_type", "broll")
    profile = spec.get("profile", "production")
    breakdown = []

    def _resolve(category: str) -> str:
        return resolve_adapter(models, category, video_type, profile)

    def _add(step_name: str, adapter_name: str):
        cost = COST_PER_STEP.get(adapter_name, 0.0)
        breakdown.append({
            "step": step_name,
            "adapter": adapter_name,
            "cost": cost,
        })

    if video_type == "broll":
        shots = spec.get("shots", [])
        image_adapter = _resolve("image_gen")
        video_adapter = _resolve("video_gen")
        upscale_adapter = _resolve("upscale")

        for i in range(len(shots)):
            _add(f"image_gen.shot_{i + 1}", image_adapter)
            _add(f"video_gen.shot_{i + 1}", video_adapter)
            if upscale_adapter:
                _add(f"upscale.shot_{i + 1}", upscale_adapter)

        tts_adapter = _resolve("tts")
        music_adapter = _resolve("music")
        _add("tts", tts_adapter)
        _add("music", music_adapter)

        ffmpeg_adapter = _resolve("ffmpeg")
        _add("merge_videos", ffmpeg_adapter)
        _add("mix_audio", ffmpeg_adapter)

    elif video_type == "talking_head":
        shots = spec.get("shots", [])
        image_adapter = _resolve("image_gen")
        image_upscale_adapter = _resolve("image_upscale")
        video_adapter = _resolve("video_gen")
        upscale_adapter = _resolve("upscale")
        ffmpeg_adapter = _resolve("ffmpeg")

        _add("image_gen.anchor", image_adapter)
        if image_upscale_adapter:
            _add("image_upscale.anchor", image_upscale_adapter)
        for i in range(len(shots)):
            _add(f"video_gen.shot_{i + 1}", video_adapter)
            if upscale_adapter:
                _add(f"upscale.shot_{i + 1}", upscale_adapter)
        if len(shots) > 1:
            _add("merge_videos", ffmpeg_adapter)

    elif video_type == "slideshow":
        slides = spec.get("slides", [])
        music_adapter = _resolve("music")
        ffmpeg_adapter = _resolve("ffmpeg")
        image_adapter = _resolve("image_gen")

        for i in range(len(slides)):
            if image_adapter:
                _add(f"image_gen.bg_{i + 1}", image_adapter)
            _add(f"pil_render.slide_{i + 1}", "pil_render")
        _add("music", music_adapter)
        _add("assemble_slideshow", ffmpeg_adapter)

    elif video_type == "video":
        shots = spec.get("shots", [])
        image_adapter = _resolve("image_gen")
        video_adapter = _resolve("video_gen")
        upscale_adapter = _resolve("upscale")

        for i, shot in enumerate(shots):
            shot_id = shot.get("shot_id", f"shot_{i + 1}")
            if shot.get("start_frame"):
                # Pre-generated frame — no image cost
                pass
            elif shot.get("derive_from"):
                # Derived frame — nano edit cost
                _add(f"image_edit.{shot_id}", "fal_nano_banana_edit")
            elif shot.get("chain_from"):
                # Chained shot — no image cost
                pass
            else:
                # Independent shot — full image gen cost
                _add(f"image_gen.{shot_id}", image_adapter)
            _add(f"video_gen.{shot_id}", video_adapter)
            if upscale_adapter:
                _add(f"upscale.{shot_id}", upscale_adapter)

        # Optional audio layers
        narration = spec.get("narration")
        music = spec.get("music")
        if narration and isinstance(narration, dict) and narration.get("script"):
            tts_adapter = _resolve("tts")
            _add("tts", tts_adapter)
        if music and isinstance(music, dict) and (music.get("mood") or music.get("composition_plan")):
            music_adapter = _resolve("music")
            _add("music", music_adapter)

        ffmpeg_adapter = _resolve("ffmpeg")
        if len(shots) > 1:
            _add("merge_videos", ffmpeg_adapter)
        if narration or music:
            _add("mix_audio", ffmpeg_adapter)

    elif video_type == "motion_control":
        image_adapter = _resolve("image_gen")
        video_adapter = _resolve("video_gen")
        ffmpeg_adapter = _resolve("ffmpeg")

        _add("download_clip", ffmpeg_adapter)
        _add("extract_frame", ffmpeg_adapter)
        _add("image_gen.character_frame", image_adapter)
        _add("video_gen.motion_control", video_adapter)

    total = sum(item["cost"] for item in breakdown)

    return {
        "total": round(total, 2),
        "breakdown": breakdown,
        "currency": "USD",
    }


def estimate_dag_cost(dag, skip_cached: bool = True) -> dict:
    """Estimate cost from a built DAG, optionally skipping cached steps.

    Unlike estimate_cost() which works on specs before the DAG exists,
    this runs after cache keys are computed and checks the asset cache
    to determine which steps will actually execute.
    """
    from workflow.asset_cache import check_cache

    breakdown = []
    for step_id, step in dag.steps.items():
        cost = COST_PER_STEP.get(step.adapter_name, 0.0)
        cached = skip_cached and check_cache(step) is not None
        breakdown.append({
            "step": step_id,
            "adapter": step.adapter_name,
            "cost": 0.0 if cached else cost,
            "cached": cached,
        })

    total = sum(item["cost"] for item in breakdown)
    cached_count = sum(1 for item in breakdown if item.get("cached"))

    return {
        "total": round(total, 2),
        "breakdown": breakdown,
        "currency": "USD",
        "cached_steps": cached_count,
        "total_steps": len(breakdown),
    }


def estimate_pipeline_cost(pipeline: dict) -> dict:
    """Estimate cost directly from a pipeline.json dict.

    Unlike estimate_cost() which works on production specs and resolves
    adapters via profiles, this works on the compiled pipeline where
    every node already has its adapter specified.
    """
    breakdown = []
    for node in pipeline.get("nodes", []):
        adapter = node.get("adapter", "")
        cost = COST_PER_STEP.get(adapter, 0.0)
        breakdown.append({
            "step": node.get("id", "unknown"),
            "adapter": adapter,
            "cost": cost,
        })
    total = sum(item["cost"] for item in breakdown)
    return {
        "total": round(total, 2),
        "breakdown": breakdown,
        "currency": "USD",
    }


def estimate_character_sheet_cost(
    num_faces: int = 3,
    num_shots: int = 4,
    scene_placement_adapter: str = "fal_nano_banana_edit",
    video_adapter: str = "fal_sora_v2",
) -> dict:
    """Estimate cost for the character sheet workflow.

    Character sheet workflow: generate face refs → place in scenes → video gen.
    Sheet is one-time per character; placement + video per concept.

    Returns:
        dict with keys: sheet_cost, placement_cost, video_cost, total, breakdown.
    """
    sheet_cost = num_faces * COST_PER_STEP.get("fal_nano_banana_v2", 0.05)
    placement_cost = num_shots * COST_PER_STEP.get(scene_placement_adapter, 0.15)
    video_cost = num_shots * COST_PER_STEP.get(video_adapter, 4.00)
    total = sheet_cost + placement_cost + video_cost

    return {
        "sheet_cost": round(sheet_cost, 2),
        "placement_cost": round(placement_cost, 2),
        "video_cost": round(video_cost, 2),
        "total": round(total, 2),
        "breakdown": (
            f"Character sheet ({num_faces} faces): ${sheet_cost:.2f} | "
            f"Scene placement ({num_shots} shots): ${placement_cost:.2f} | "
            f"Video gen ({num_shots} clips): ${video_cost:.2f} | "
            f"Total: ${total:.2f}"
        ),
    }
