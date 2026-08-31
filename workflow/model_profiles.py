"""Model profiles — default adapter combos per video type.

Each profile maps video_type -> model_category -> adapter name.
Templates read from here when the spec doesn't override a model.

Profiles:
  - production: Best quality, higher cost
  - cheap: Fast/low-cost for testing workflows
"""

PROFILES: dict[str, dict[str, dict[str, str]]] = {
    "production": {
        "broll": {
            "image_gen": "fal_nano_banana_v2",
            "video_gen": "fal_veo_v3_flf",
            "upscale": "fal_topaz_upscale",
            "tts": "elevenlabs_tts",
            "music": "elevenlabs_music",
            "ffmpeg": "local_ffmpeg",
        },
        "talking_head": {
            "image_gen": "fal_nano_banana_v2",
            "image_upscale": "freepik_magnific_upscale",
            "video_gen": "fal_veo_v3_flf",
            "upscale": "fal_topaz_upscale",
            "ffmpeg": "local_ffmpeg",
        },
        "slideshow": {
            "image_gen": "fal_nano_banana_v2",
            "music": "elevenlabs_music",
            "ffmpeg": "local_ffmpeg",
        },
        "motion_control": {
            "image_gen": "fal_nano_banana_v2",
            "video_gen": "fal_kling_v3",
            "ffmpeg": "local_ffmpeg",
        },
        "video": {
            "image_gen": "fal_nano_banana_v2",
            "video_gen": "fal_veo_v3_flf",
            "upscale": "fal_topaz_upscale",
            "tts": "elevenlabs_tts",
            "music": "elevenlabs_music",
            "ffmpeg": "local_ffmpeg",
        },
    },
    "cheap": {
        "broll": {
            "image_gen": "fal_nano_banana_v2",
            "video_gen": "fal_kling_v2",
            "upscale": "fal_topaz_upscale",
            "tts": "elevenlabs_tts",
            "music": "elevenlabs_music",
            "ffmpeg": "local_ffmpeg",
        },
        "talking_head": {
            "image_gen": "fal_nano_banana_v2",
            "image_upscale": "freepik_magnific_upscale",
            "video_gen": "fal_kling_v2",
            "upscale": "fal_topaz_upscale",
            "ffmpeg": "local_ffmpeg",
        },
        "slideshow": {
            "image_gen": "fal_nano_banana_v2",
            "music": "elevenlabs_music",
            "ffmpeg": "local_ffmpeg",
        },
        "motion_control": {
            "image_gen": "fal_nano_banana_v2",
            "video_gen": "fal_kling_v2",
            "ffmpeg": "local_ffmpeg",
        },
        "video": {
            "image_gen": "fal_nano_banana_v2",
            "video_gen": "fal_kling_v2",
            "upscale": "fal_topaz_upscale",
            "tts": "elevenlabs_tts",
            "music": "elevenlabs_music",
            "ffmpeg": "local_ffmpeg",
        },
    },
}

DEFAULT_PROFILE = "production"


def get_defaults(video_type: str, profile: str = DEFAULT_PROFILE) -> dict[str, str]:
    """Return default adapter names for a video type and profile.

    Args:
        video_type: "broll", "talking_head", or "slideshow"
        profile: "production" or "cheap"

    Returns:
        Dict mapping model category to adapter name.
    """
    if profile not in PROFILES:
        raise ValueError(
            f"Unknown profile '{profile}'. Must be one of: {', '.join(sorted(PROFILES))}"
        )
    return PROFILES[profile].get(video_type, {})


def resolve_all(spec: dict) -> dict[str, dict[str, str]]:
    """Resolve all adapter names for a spec and return a fully populated models dict.

    Merges profile defaults with any explicit overrides in spec["models"].
    The returned dict has one entry per category, each with an "adapter" key.
    This makes the spec fully self-contained and replayable.
    """
    video_type = spec.get("video_type", "broll")
    profile = spec.get("profile", DEFAULT_PROFILE)
    spec_models = spec.get("models", {})
    defaults = get_defaults(video_type, profile)

    resolved: dict[str, dict[str, str]] = {}
    for category, default_adapter in defaults.items():
        cat_config = dict(spec_models.get(category, {}))
        if "adapter" not in cat_config:
            cat_config["adapter"] = default_adapter
        resolved[category] = cat_config

    # Preserve any extra categories from spec_models not in defaults
    for category, cat_config in spec_models.items():
        if category not in resolved:
            resolved[category] = dict(cat_config)

    return resolved


def resolve_adapter(spec_models: dict, category: str, video_type: str, profile: str = DEFAULT_PROFILE) -> str:
    """Get the adapter for a category: spec override wins, else profile default.

    Args:
        spec_models: The spec's "models" dict.
        category: e.g. "image_gen", "video_gen", "tts", "music", "ffmpeg"
        video_type: e.g. "broll", "talking_head", "slideshow"
        profile: "production" or "cheap"

    Returns:
        Adapter name string.
    """
    cat_config = spec_models.get(category, {})
    if "adapter" in cat_config:
        return cat_config["adapter"]
    defaults = get_defaults(video_type, profile)
    return defaults.get(category, "")
