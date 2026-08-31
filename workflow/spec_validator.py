"""Production spec validator.

Validates a production spec before execution, catching configuration errors
early rather than failing mid-pipeline.

Checks structural issues (missing fields, wrong types, bad adapters) and
hard limits (prompt length, duration). Does NOT police prompt content or
creative quality — that's the job of skills and subagents.
"""

import os
import re

# Known adapter names that can appear in the models block.
KNOWN_ADAPTERS = {
    "fal_dreamina_v3",
    "fal_nano_banana_edit",
    "fal_nano_banana_v2",
    "fal_nano_banana_scene_transfer",
    "fal_kling_v2",
    "fal_kling_v3",
    "fal_kling_v3_ref",  # deprecated — use fal_kling_v3 with black start frame + elements
    "fal_seedance_v1_5",
    "fal_ltx_v2",
    "fal_hailuo_02",
    "fal_veo_v3_flf",
    "fal_sora_v2",
    "fal_sora_v2_t2v",
    "fal_veo_v3_t2v",
    "fal_kling_v3_t2v",
    "elevenlabs_tts",
    "elevenlabs_music",
    "elevenlabs_voice_design",
    "fal_topaz_upscale",
    "freepik_magnific_upscale",
    "local_ffmpeg",
    "ffmpeg_concat",
    "ffmpeg_mix_audio",
    "ffmpeg_extract_last_frame",
    "ffmpeg_extract_first_frame",
    "pil_render",
}

VALID_VIDEO_TYPES = {"broll", "talking_head", "slideshow", "motion_control", "video"}
VALID_PROFILES = {"production", "cheap"}
VALID_ASPECT_RATIOS = {"9:16", "16:9", "1:1", "4:5", "3:4", "3:2"}

# Video adapters that support character reference images for consistency.
# If character.reference_photos is set, the video adapter MUST be in this set.
ADAPTERS_WITH_CHARACTER_REF = {
    "fal_kling_v3",           # elements[].frontal_image_url + reference_image_urls
}

# Maximum prompt character limits per video adapter.
# Exceeding these causes API errors or silent truncation.
PROMPT_CHAR_LIMITS: dict[str, int] = {
    "fal_kling_v2":        2500,
    "fal_kling_v3":        2500,
    "fal_sora_v2":         5000,
    "fal_sora_v2_t2v":    5000,
    "fal_veo_v3_t2v":     20000,
    "fal_kling_v3_t2v":   2500,
    "fal_veo_v3_flf":      20000,
    "fal_ltx_v2":          4000,
    "fal_hailuo_02":       4000,
    "fal_seedance_v1_5":   3000,
}

# Required fields in a Nano Banana structured spec.
_NANO_BANANA_REQUIRED_PROMPT_FIELDS = {
    "scene_description",
    "subject_pose_and_expression",
    "background_and_environment",
    "lighting",
    "camera_and_framing",
    "overall_style",
}

# Required model categories per video type.
REQUIRED_MODELS = {
    "broll": {"image_gen", "video_gen", "tts", "music", "ffmpeg"},
    "talking_head": {"image_gen", "video_gen"},
    "slideshow": {"music", "ffmpeg"},
    "motion_control": {"image_gen", "video_gen"},
    "video": {"image_gen", "video_gen"},
}


def validate_spec(spec: dict) -> list[str]:
    """Validate a production spec. Returns a list of error messages (empty = valid).

    Checks structural issues only:
    - Required top-level fields and types
    - video_type, profile, aspect_ratio are valid
    - models has required adapters for the video_type
    - Adapter names are known
    - shots/slides present and well-formed
    - Prompt length within adapter limits
    - narration and music configuration
    - output configuration
    """
    errors = []

    # --- Required top-level fields ---
    for field in ("version", "video_type", "run_name", "models", "output"):
        if field not in spec:
            errors.append(f"Missing required top-level field: '{field}'")

    if "video_type" not in spec or "models" not in spec:
        return errors

    # --- video_type validation ---
    video_type = spec["video_type"]
    if video_type not in VALID_VIDEO_TYPES:
        errors.append(
            f"Invalid video_type '{video_type}'. "
            f"Must be one of: {', '.join(sorted(VALID_VIDEO_TYPES))}"
        )
        return errors

    # --- models validation ---
    models = spec["models"]
    if not isinstance(models, dict):
        errors.append("'models' must be a dict")
        return errors

    # --- profile validation ---
    profile = spec.get("profile", "production")
    if profile not in VALID_PROFILES:
        errors.append(
            f"Invalid profile '{profile}'. Must be one of: {', '.join(sorted(VALID_PROFILES))}"
        )

    # --- max_budget validation ---
    max_budget = spec.get("max_budget")
    if max_budget is not None:
        if not isinstance(max_budget, (int, float)) or max_budget <= 0:
            errors.append(
                f"'max_budget' must be a positive number (got {max_budget!r})"
            )

    # --- aspect_ratio validation ---
    aspect_ratio = spec.get("aspect_ratio", "9:16")
    if aspect_ratio not in VALID_ASPECT_RATIOS:
        errors.append(
            f"Invalid aspect_ratio '{aspect_ratio}'. Must be one of: {', '.join(sorted(VALID_ASPECT_RATIOS))}"
        )

    # Resolve profile defaults
    from workflow.model_profiles import get_defaults
    profile_defaults = get_defaults(video_type, profile)

    required = set(REQUIRED_MODELS[video_type])

    for category in required:
        has_in_spec = category in models
        has_in_profile = category in profile_defaults and profile_defaults[category]
        if not has_in_spec and not has_in_profile:
            errors.append(f"Missing required model category '{category}' for video_type '{video_type}'")
        elif has_in_spec:
            if not isinstance(models[category], dict):
                errors.append(f"Model category '{category}' must be a dict with at least an 'adapter' key")
            elif "adapter" not in models[category]:
                errors.append(f"Model category '{category}' missing 'adapter' key")

    # --- Validate adapter names ---
    for category, config in models.items():
        if isinstance(config, dict):
            adapter = config.get("adapter", "")
            if adapter and adapter not in KNOWN_ADAPTERS:
                errors.append(
                    f"Unknown adapter '{adapter}' in models.{category}. "
                    f"Known adapters: {', '.join(sorted(KNOWN_ADAPTERS))}"
                )
            fallback = config.get("fallback", "")
            if fallback and fallback not in KNOWN_ADAPTERS:
                errors.append(
                    f"Unknown fallback adapter '{fallback}' in models.{category}. "
                    f"Known adapters: {', '.join(sorted(KNOWN_ADAPTERS))}"
                )

    # --- shots / slides validation ---
    if video_type in ("broll", "talking_head", "video"):
        shots = spec.get("shots")
        if shots is None:
            errors.append(f"'shots' is required for video_type '{video_type}'")
        elif not isinstance(shots, list) or len(shots) == 0:
            errors.append(f"'shots' must be a non-empty list for video_type '{video_type}'")
        else:
            seen_ids: set[str] = set()
            for i, shot in enumerate(shots):
                shot_id = shot.get("shot_id", f"shot_{i + 1}")

                if shot_id in seen_ids:
                    errors.append(f"Duplicate shot_id '{shot_id}' — shot IDs must be unique")
                seen_ids.add(shot_id)

                if not shot.get("video_prompt"):
                    errors.append(
                        f"Shot '{shot_id}' missing 'video_prompt'. "
                        "Write a finished video prompt before production."
                    )

                # --- Relationship field validation ---
                rel_fields = [f for f in ("start_frame", "chain_from", "derive_from") if shot.get(f)]
                if len(rel_fields) > 1:
                    errors.append(
                        f"Shot '{shot_id}' has multiple relationship fields: "
                        f"{', '.join(rel_fields)}. Use only one of: "
                        "start_frame, chain_from, derive_from."
                    )

                start_frame = shot.get("start_frame")
                if start_frame:
                    if not isinstance(start_frame, str):
                        errors.append(
                            f"Shot '{shot_id}' start_frame must be a file path string."
                        )
                    elif not os.path.exists(start_frame):
                        errors.append(
                            f"Shot '{shot_id}' start_frame not found: '{start_frame}'. "
                            "Generate the frame with try-frame first."
                        )

                chain_ref = shot.get("chain_from")
                if chain_ref and chain_ref not in seen_ids:
                    errors.append(
                        f"Shot '{shot_id}' has chain_from='{chain_ref}' but that shot "
                        "hasn't been defined yet. Chained shots must come after their source."
                    )

                derive_ref = shot.get("derive_from")
                if derive_ref:
                    if derive_ref not in seen_ids:
                        errors.append(
                            f"Shot '{shot_id}' has derive_from='{derive_ref}' but that shot "
                            "hasn't been defined yet. Derived shots must come after their source."
                        )
                    if not shot.get("image_prompt"):
                        errors.append(
                            f"Shot '{shot_id}' derives from '{derive_ref}' but has no "
                            "'image_prompt' describing the variation."
                        )

                # duration validation
                duration = shot.get("duration")
                if duration is not None:
                    if not isinstance(duration, (int, float)) or duration <= 0:
                        errors.append(
                            f"Shot '{shot_id}' has invalid duration '{duration}'. "
                            "Must be a positive number."
                        )
                    elif duration > 12:
                        errors.append(
                            f"Shot '{shot_id}' duration {duration}s exceeds max (12s). "
                            "Break into multiple shots."
                        )

                # --- Prompt length limit (hard API constraint) ---
                video_prompt = shot.get("video_prompt", "")
                if video_prompt:
                    adapter = _resolve_video_adapter(models, profile)
                    prompt_len = len(video_prompt.strip())
                    char_limit = PROMPT_CHAR_LIMITS.get(adapter)
                    if char_limit and prompt_len > char_limit:
                        errors.append(
                            f"Shot '{shot_id}' video_prompt is {prompt_len} chars but adapter "
                            f"'{adapter}' has a {char_limit}-char limit. "
                            f"Condense the prompt by ~{prompt_len - char_limit} chars."
                        )

                # --- Nano Banana spec validation ---
                nano_spec = shot.get("nano_banana_spec")
                if nano_spec is not None:
                    _validate_nano_banana_spec(errors, nano_spec, shot_id)

    # --- Character validation ---
    character = spec.get("character")
    if video_type == "talking_head":
        if character is None:
            errors.append(
                "'character' is required for video_type 'talking_head'. "
                "Provide a character block with 'name' and 'description'."
            )
        elif not isinstance(character, dict):
            errors.append("'character' must be a dict with 'name' and 'description'")
        else:
            if not character.get("name"):
                errors.append("'character.name' is required for talking_head")
            if not character.get("description"):
                errors.append("'character.description' is required for talking_head")

    # --- Character reference_photos validation ---
    if isinstance(character, dict) and character.get("reference_photos"):
        ref_photos = character["reference_photos"]
        if not isinstance(ref_photos, list):
            errors.append(
                "'character.reference_photos' must be a list of file paths."
            )
        else:
            for i, photo_path in enumerate(ref_photos):
                if not isinstance(photo_path, str):
                    errors.append(
                        f"'character.reference_photos[{i}]' must be a string path, "
                        f"got {type(photo_path).__name__}"
                    )
                elif not os.path.exists(photo_path):
                    errors.append(
                        f"Character reference photo not found: '{photo_path}'. "
                        "Generate reference photos with the create-persona skill first."
                    )

            # Verify the video adapter supports reference images
            if ref_photos and video_type in ("broll", "talking_head", "motion_control", "video"):
                video_adapter = _resolve_video_adapter(models, profile)
                if video_adapter and video_adapter not in ADAPTERS_WITH_CHARACTER_REF:
                    errors.append(
                        f"Character has reference_photos but the video adapter "
                        f"'{video_adapter}' does not support character reference images. "
                        f"Adapters with character ref support: "
                        f"{', '.join(sorted(ADAPTERS_WITH_CHARACTER_REF))}. "
                        f"Either switch the video_gen adapter or remove reference_photos."
                    )

    if video_type == "slideshow":
        slides = spec.get("slides")
        if slides is None:
            errors.append("'slides' is required for video_type 'slideshow'")
        elif not isinstance(slides, list) or len(slides) == 0:
            errors.append("'slides' must be a non-empty list for video_type 'slideshow'")

    # --- narration validation ---
    if video_type == "broll":
        narration = spec.get("narration")
        if narration is None:
            errors.append("'narration' is required for video_type 'broll'")
        elif not isinstance(narration, dict):
            errors.append("'narration' must be a dict")
        else:
            if not narration.get("script"):
                errors.append("'narration.script' is required")
            if not narration.get("voice_id") and not narration.get("voice_description"):
                errors.append(
                    "'narration' must have 'voice_id' or 'voice_description'. "
                    "Use try-voice to preview voices first."
                )

    # --- music validation ---
    if video_type in ("broll", "slideshow"):
        music = spec.get("music")
        if music is None:
            errors.append(f"'music' is required for video_type '{video_type}'")
        elif not isinstance(music, dict):
            errors.append("'music' must be a dict")
        elif not music.get("mood") and not music.get("composition_plan"):
            errors.append("'music' must have either 'mood' or 'composition_plan'")

    # --- motion_control specific validation ---
    if video_type == "motion_control":
        ref = spec.get("reference_clip")
        if ref is None:
            errors.append("'reference_clip' is required for video_type 'motion_control'")
        elif not isinstance(ref, dict):
            errors.append("'reference_clip' must be a dict")
        elif not ref.get("url"):
            errors.append("'reference_clip.url' is required")

    # --- output validation ---
    output = spec.get("output")
    if output is not None:
        if not isinstance(output, dict):
            errors.append("'output' must be a dict")
        else:
            if not output.get("dir"):
                errors.append("'output.dir' is required")
            if not output.get("final_filename"):
                errors.append("'output.final_filename' is required")

    return errors


def _resolve_video_adapter(models: dict, profile: str) -> str:
    """Get the video_gen adapter from spec models or profile defaults."""
    cat_config = models.get("video_gen", {})
    if isinstance(cat_config, dict) and cat_config.get("adapter"):
        return cat_config["adapter"]
    from workflow.model_profiles import get_defaults
    for vt in ("broll", "talking_head", "motion_control"):
        defaults = get_defaults(vt, profile)
        if "video_gen" in defaults:
            return defaults["video_gen"]
    return ""


def _validate_nano_banana_spec(
    errors: list[str],
    spec: object,
    shot_id: str,
) -> None:
    """Check that a Nano Banana spec has the required structure."""
    if not isinstance(spec, dict):
        errors.append(
            f"Shot '{shot_id}' nano_banana_spec must be a dict, got {type(spec).__name__}"
        )
        return

    prompt_block = spec.get("prompt")
    if not isinstance(prompt_block, dict):
        errors.append(
            f"Shot '{shot_id}' nano_banana_spec missing 'prompt' dict. "
            "See nano-banana-prompting skill reference for the full schema."
        )
        return

    missing = _NANO_BANANA_REQUIRED_PROMPT_FIELDS - set(prompt_block.keys())
    if missing:
        errors.append(
            f"Shot '{shot_id}' nano_banana_spec.prompt missing required fields: "
            f"{', '.join(sorted(missing))}. "
            "See nano-banana-prompting skill reference for the full schema."
        )
