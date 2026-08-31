"""Prompt builder — prepares adapter configs from production spec fields.

Video prompts (Veo, Sora, Kling, etc.) are written at spec-building time
by Claude following model-specific prompting guides and stored as
``shot.video_prompt``. This module extracts them for the DAG step config.

Image prompts are built from structured creative fields (scene, subject,
lighting, etc.) into Nano Banana JSON specs.

Music and TTS configs are assembled from the spec's music/narration blocks.
"""

import json


def _dot(s: str) -> str:
    """Ensure string ends with exactly one period."""
    s = s.rstrip()
    return s if s.endswith(".") else f"{s}."


# ── Technical negative prompt (AI artifact prevention only) ────────────────
# These prevent technical AI artifacts, NOT creative choices.
# Creative negatives (lighting style, environment type) come from the concept.

_TECHNICAL_NEGATIVE_PROMPT = [
    "watermark",
    "text overlays",
    "text artifacts",
    "distorted hands",
    "extra fingers",
    "AI uncanny valley",
    "plastic skin",
]


# ── Nano Banana (Image Gen) ────────────────────────────────────────────────


def build_nano_banana_spec(shot: dict, spec: dict | None = None) -> dict:
    """Build a full Nano Banana JSON spec from structured creative fields.

    Args:
        shot: The shot dict with creative fields (scene, subject, lighting, etc.)
        spec: The full production spec (for aspect_ratio, character, etc.)

    Returns:
        A complete Nano Banana spec dict ready for the adapter's nano_banana_spec key.
    """
    spec = spec or {}
    character = spec.get("character", {})
    aspect_ratio = shot.get("aspect_ratio") or spec.get("aspect_ratio", "9:16")

    # Map aspect ratio to orientation
    orientation_map = {
        "9:16": "vertical",
        "16:9": "horizontal",
        "1:1": "square",
        "4:5": "vertical",
        "3:4": "vertical",
        "3:2": "horizontal",
    }

    # ── Build the prompt object ────────────────────────────────────────

    scene = shot.get("scene", "")
    subject = shot.get("subject", "")
    action = shot.get("action", "")
    props = shot.get("props", "")
    lighting = shot.get("lighting", "")
    camera = shot.get("camera", "")
    color_grade = shot.get("color_grade", "")
    style = shot.get("style", "")
    wardrobe_top = shot.get("wardrobe_top", "")
    wardrobe_bottom = shot.get("wardrobe_bottom", "")
    footwear = shot.get("footwear", "")
    background = shot.get("background", "")

    # Build scene_description — the most important field
    scene_parts = []

    # Character integration — lead with character if present
    if character:
        char_name = character.get("name", "")
        char_desc = character.get("description", "")
        char_outfit = character.get("outfit", "")
        if char_name and char_desc:
            scene_parts.append(_dot(f"{char_name}: {char_desc}"))
        if char_outfit and not wardrobe_top:
            wardrobe_top = char_outfit

    if scene:
        scene_parts.append(_dot(scene))
    if subject:
        scene_parts.append(_dot(subject))
    if action:
        scene_parts.append(_dot(action))
    if props:
        scene_parts.append(_dot(f"Props visible in frame: {props}"))

    scene_description = " ".join(scene_parts) if scene_parts else scene
    if not scene_description.strip():
        raise ValueError(
            f"Shot '{shot.get('shot_id', '?')}' has empty scene_description. "
            "Provide at least 'scene' or 'subject' in the shot fields."
        )

    # Build subject_pose_and_expression
    pose_parts = []
    if subject:
        pose_parts.append(subject)
    if action:
        pose_parts.append(action)
    subject_pose = ". ".join(pose_parts) if pose_parts else "Natural, relaxed pose."

    # Build background_and_environment
    bg_parts = []
    if background:
        bg_parts.append(f"{background}.")
    elif scene:
        bg_parts.append(f"{scene}.")
    if props:
        bg_parts.append(f"Visible props: {props}.")
    background_env = " ".join(bg_parts) if bg_parts else ""

    # All creative fields are REQUIRED — no silent defaults.
    # If any are missing, the concept didn't specify them. Fix the concept.
    shot_id = shot.get("shot_id", "?")

    if not lighting:
        raise ValueError(
            f"Shot '{shot_id}' missing 'lighting'. "
            "Specify lighting in the concept (e.g., 'golden hour through kitchen window', "
            "'overhead fluorescent gym lighting', 'ring light + laptop glow')."
        )

    if not color_grade:
        raise ValueError(
            f"Shot '{shot_id}' missing 'color_grade'. "
            "Specify color grading in the concept (e.g., 'warm filmic, slight grain', "
            "'cool desaturated, clinical', 'bright and slightly overexposed')."
        )

    # Build camera_and_framing
    orientation_label = "Vertical" if orientation_map.get(aspect_ratio, "vertical") == "vertical" else "Horizontal"
    camera_parts = [f"{orientation_label} {aspect_ratio}"]
    if not camera:
        raise ValueError(
            f"Shot '{shot_id}' missing 'camera'. "
            "Specify camera/framing in the concept (e.g., 'close-up, 50mm, shallow DOF', "
            "'wide shot, 24mm, deep focus', 'selfie angle, front-facing phone camera')."
        )
    camera_parts.append(camera)
    camera_framing = ". ".join(camera_parts)

    if not style:
        raise ValueError(
            f"Shot '{shot_id}' missing 'style'. "
            "Specify overall style in the concept (e.g., 'phone camera UGC, slightly shaky', "
            "'cinematic 35mm film', 'clean studio product shot')."
        )

    # ── Assemble the full spec ─────────────────────────────────────────

    nano_spec = {
        "schema_version": "1.0",
        "meta": {
            "intent": _build_intent(shot, spec),
            "aspect_ratio": aspect_ratio,
            "orientation": orientation_map.get(aspect_ratio, "vertical"),
        },
        "prompt": {
            "scene_description": scene_description,
            "subject_pose_and_expression": subject_pose,
            "clothing_top": wardrobe_top or "Not specified.",
            "clothing_bottom": wardrobe_bottom or "Not visible.",
            "footwear": footwear or "Not visible.",
            "background_and_environment": background_env,
            "lighting": lighting,
            "color_and_grading": color_grade,
            "camera_and_framing": camera_framing,
            "branding_and_text": "None.",
            "overall_style": style,
        },
        "negative_prompt": _build_negative_prompt(shot),
        "generation_settings": {
            "style": "photorealistic",
            "quality": "high",
            "aspect_ratio": aspect_ratio,
        },
    }

    return nano_spec


def _build_intent(shot: dict, spec: dict) -> str:
    """Build a concise intent line for the Nano Banana meta block."""
    video_type = spec.get("video_type", "broll")
    scene = shot.get("scene", "")
    if video_type == "talking_head":
        return f"Wellness UGC talking head — anchor frame. {scene}"
    if video_type == "video":
        return f"Wellness video — start frame. {scene}"
    return f"Cinematic b-roll frame for a wellness ad. {scene}"


def _build_negative_prompt(shot: dict) -> list[str]:
    """Build negative prompt list from technical defaults + shot-specific."""
    negatives = list(_TECHNICAL_NEGATIVE_PROMPT)
    extra = shot.get("negative_prompt", [])
    if isinstance(extra, str):
        extra = [s.strip() for s in extra.split(",") if s.strip()]
    for item in extra:
        if item not in negatives:
            negatives.append(item)
    return negatives


def nano_banana_prompt_to_config(shot: dict, spec: dict | None = None) -> dict:
    """Build config dict for the image gen adapter from creative fields.

    Returns a dict with 'nano_banana_spec', 'prompt', 'negative_prompt', and
    'aspect_ratio' keys ready to merge into the step config.
    """
    spec = spec or {}
    aspect_ratio = shot.get("aspect_ratio") or spec.get("aspect_ratio", "9:16")

    # Pre-written spec or prompt from spec-building time
    pre_spec = shot.get("nano_banana_spec")
    pre_prompt = shot.get("image_prompt")

    if pre_spec and isinstance(pre_spec, dict):
        return {"nano_banana_spec": pre_spec}

    # Build from structured creative fields
    nano_spec = build_nano_banana_spec(shot, spec)
    return {"nano_banana_spec": nano_spec}


def nano_banana_edit_to_config(shot: dict, spec: dict | None = None) -> dict:
    """Build config dict for the Nano Banana Edit adapter.

    Passes the reference image directly to the model with a flat text prompt.
    For better environment preservation, use scene_transfer_to_config() instead —
    it describes the reference via Gemini first, then merges changes cleanly.

    Shot fields used:
        reference_image_url (str): Public URL of the reference image.
        reference_image (str): Local file path (uploaded to Supabase by the adapter).
        image_prompt (str): What to put in the scene (required).
        aspect_ratio (str): Override aspect ratio (default "auto" — preserves reference).
    """
    spec = spec or {}

    prompt = shot.get("image_prompt", "")
    if not prompt:
        raise ValueError(
            f"Shot '{shot.get('shot_id', '?')}' is missing 'image_prompt' for the edit adapter. "
            "Describe what you want in the scene — the reference image provides the lighting."
        )

    config: dict = {"prompt": prompt}

    # Reference image: prefer URL (no upload needed), fall back to local path
    ref_url = shot.get("reference_image_url")
    ref_path = shot.get("reference_image")
    if ref_url:
        config["reference_image_url"] = ref_url
    elif ref_path:
        config["reference_image"] = ref_path
    else:
        raise ValueError(
            f"Shot '{shot.get('shot_id', '?')}' is missing 'reference_image_url' or "
            "'reference_image'. Provide a reference photo for the edit adapter — "
            "this is the image whose lighting and composition will be preserved."
        )

    aspect_ratio = shot.get("aspect_ratio") or spec.get("aspect_ratio", "auto")
    config["aspect_ratio"] = aspect_ratio

    return config


def scene_transfer_to_config(shot: dict, spec: dict | None = None) -> dict:
    """Build config dict for the Nano Banana Scene Transfer adapter.

    CRITICAL: The 'changes' prompt must be SURGICAL — only describe what's
    DIFFERENT from the reference image. The adapter's Gemini step captures
    everything else (lighting, surfaces, camera angle, color palette, depth
    of field, background detail) from the reference automatically.

    DO NOT include in changes:
      - Lighting (comes from reference)
      - Camera angle/framing (comes from reference)
      - Background/setting (comes from reference)
      - Color grade (comes from reference)

    DO include in changes:
      - Subject description (who is in the shot)
      - Wardrobe (what they're wearing)
      - Expression/pose (how they look/feel)
      - Props they're holding/interacting with
      - Accessories (jewelry, glasses, etc.)

    Shot fields used:
        reference_image_url (str): Public URL of the reference image.
        reference_image (str): Local file path.
        image_prompt (str): Pre-written changes prompt (used as-is if present).
        aspect_ratio (str): Override aspect ratio (default from spec).

    Falls back to building changes from character + wardrobe + action fields
    if image_prompt is not pre-written.
    """
    spec = spec or {}
    character = spec.get("character", {})

    # Reference image: prefer URL (no upload needed), fall back to local path
    ref_url = shot.get("reference_image_url")
    ref_path = shot.get("reference_image")
    if not ref_url and not ref_path:
        raise ValueError(
            f"Shot '{shot.get('shot_id', '?')}' is missing 'reference_image_url' or "
            "'reference_image'. Scene transfer requires a reference photo."
        )

    # Build the changes prompt — ONLY the delta from the reference
    changes = shot.get("image_prompt", "")
    if not changes:
        # Build from structured fields — subject/wardrobe/expression only
        parts = []

        # Subject description (character)
        if character.get("description"):
            parts.append(f"Change the subject to: {_dot(character['description'])}")

        # Wardrobe
        wardrobe_parts = []
        if shot.get("wardrobe_top"):
            wardrobe_parts.append(shot["wardrobe_top"])
        if shot.get("wardrobe_bottom"):
            wardrobe_parts.append(shot["wardrobe_bottom"])
        if shot.get("footwear"):
            wardrobe_parts.append(shot["footwear"])
        if wardrobe_parts:
            parts.append(f"Wearing: {', '.join(wardrobe_parts)}.")

        # Expression/pose/action
        if shot.get("action"):
            parts.append(_dot(shot["action"]))
        if shot.get("subject"):
            parts.append(_dot(shot["subject"]))

        # Props
        if shot.get("props"):
            parts.append(f"Holding/near: {_dot(shot['props'])}")

        changes = " ".join(parts)

    if not changes:
        raise ValueError(
            f"Shot '{shot.get('shot_id', '?')}' has no changes for scene transfer. "
            "Provide 'image_prompt' (changes description) or character + wardrobe fields."
        )

    config: dict = {
        "changes": changes,
        "enable_web_search": True,
        "save_description": True,
    }

    if ref_url:
        config["reference_image_url"] = ref_url
    elif ref_path:
        config["reference_image"] = ref_path

    aspect_ratio = shot.get("aspect_ratio") or spec.get("aspect_ratio", "9:16")
    config["aspect_ratio"] = aspect_ratio

    return config


# ── Character Reference Images ─────────────────────────────────────────────

# Video adapters that accept character reference photos and their config format.
_CHARACTER_REF_FORMATS = {
    "fal_kling_v3": "elements",         # elements[].frontal_image_path + reference_image_paths
}


def build_character_ref_config(
    spec: dict,
    video_adapter: str,
    fallback_frame_from: str | None = None,
) -> dict:
    """Build adapter-specific config for character reference images.

    Reads character.reference_photos from the spec. If none are provided and
    ``fallback_frame_from`` (step ID) is given (e.g. the anchor frame generated
    by the template), uses that as the reference photo instead — so every run
    gets character consistency for free on adapters that support it.

    Returns a ``_from`` reference that the engine resolves at runtime.

    Returns empty dict if no reference photos and no fallback, or if the
    adapter doesn't support character references.
    """
    character = spec.get("character", {})
    ref_photos = character.get("reference_photos", [])

    # If no explicit photos, use fallback
    if not ref_photos or not isinstance(ref_photos, list):
        if fallback_frame_from:
            # Return a _from ref for the engine to resolve at runtime
            fmt = _CHARACTER_REF_FORMATS.get(video_adapter)
            if not fmt:
                return {}
            return {"character_ref_frame_from": fallback_frame_from}
        else:
            return {}

    fmt = _CHARACTER_REF_FORMATS.get(video_adapter)
    if not fmt:
        return {}

    if fmt == "elements":
        # Kling v3: first photo = frontal, rest = reference angles
        element = {
            "frontal_image_path": ref_photos[0],
        }
        if len(ref_photos) > 1:
            element["reference_image_paths"] = ref_photos[1:]
        return {"elements": [element]}

    return {}


# ── Video Gen (Veo, Sora, Kling, etc.) ────────────────────────────────────


def veo_prompt_to_config(shot: dict, spec: dict | None = None) -> dict:
    """Extract the finished video prompt from the shot.

    The ``video_prompt`` field must be written at spec-building time by Claude,
    following the model-specific prompting guide (Veo 6-part, Sora shot-by-shot,
    Kling 5-part, etc.). The engine passes it through to the video adapter
    untouched.

    Returns a dict with 'prompt' ready to merge into the step config.
    """
    prompt = shot.get("video_prompt", "")
    if not prompt:
        raise ValueError(
            f"Shot '{shot.get('shot_id', '?')}' is missing 'video_prompt'. "
            "Write a finished video prompt following the model-specific provider guide."
        )
    return {"prompt": prompt}


# ── ElevenLabs Music ────────────────────────────────────────────────────────


def build_music_config(music: dict, total_duration_s: int = 15) -> dict:
    """Build music adapter config with a composition plan.

    Always generates a structured composition plan from the mood/prompt and
    video duration. If a composition plan is already provided in the spec,
    passes it through.

    Args:
        music: The spec's music block.
        total_duration_s: Total video duration in seconds (for section timing).

    Returns:
        Dict ready to merge into the music step config.
    """
    # If a full composition plan is already provided, pass through
    if music.get("sections") or music.get("positiveGlobalStyles"):
        return dict(music)

    # Build a composition plan from mood/prompt + duration
    prompt = music.get("prompt", "") or music.get("mood", "calm")
    mood = music.get("mood", "calm")

    # Parse mood into positive/negative global styles
    positive_global, negative_global = _mood_to_global_styles(mood, prompt)

    # Build sections based on duration
    sections = _build_music_sections(prompt, mood, total_duration_s)

    config: dict = {
        "positiveGlobalStyles": positive_global,
        "negativeGlobalStyles": negative_global,
        "sections": sections,
    }

    if music.get("volume_db"):
        config["volume_db"] = music["volume_db"]

    return config


# ── Music mood → global styles ─────────────────────────────────────────


def _mood_to_global_styles(mood: str, prompt: str) -> tuple[list[str], list[str]]:
    """Build positive and negative global styles from the mood and prompt text.

    Uses the mood and prompt directly as style descriptors rather than
    mapping through a fixed lookup table. This lets every concept produce
    a unique musical identity instead of rotating through the same
    instrument combinations.
    """
    positive = [mood]
    negative = []

    # Parse specific instrument/texture/style mentions from the prompt
    prompt_lower = prompt.lower()

    # Split prompt into style tokens — anything comma- or space-separated
    # that looks like a musical descriptor
    for token in [t.strip() for t in prompt.replace(",", " ").split() if len(t.strip()) > 2]:
        if token not in positive:
            positive.append(token)

    # If the prompt is short (just a mood word), add the mood as-is
    if len(positive) < 3:
        positive.append(f"{mood} feel")

    # Parse explicit "no X" exclusions from the prompt
    import re
    no_matches = re.findall(r"no\s+(\w+(?:\s+\w+)?)", prompt_lower)
    for match in no_matches:
        if match not in negative:
            negative.append(match)

    return positive, negative


def _build_music_sections(prompt: str, mood: str, total_duration_s: int) -> list[dict]:
    """Build composition plan sections based on video duration.

    Follows a 3-act emotional arc:
      1. Intro — sparse, sets the mood
      2. Body — develops the theme, adds warmth
      3. Resolve — gentle landing or lift

    IMPORTANT: ElevenLabs music fades out ~2s before the end of the last
    section. To prevent dead silence at the video's tail, we add a 10s
    overshoot buffer to the final section. The calling workflow uses
    FFmpeg's ``-shortest`` flag to trim the excess when mixing.
    """
    OVERSHOOT_MS = 10_000  # extra duration on last section to avoid early fade

    if total_duration_s <= 5:
        # Single section for very short clips
        return [
            {
                "sectionName": "Full",
                "positiveLocalStyles": _section_styles(prompt, "sparse, gentle opening, single instrument"),
                "negativeLocalStyles": ["loud", "complex arrangement", "sudden changes"],
                "durationMs": total_duration_s * 1000 + OVERSHOOT_MS,
                "lines": [],
            }
        ]

    if total_duration_s <= 10:
        # Two sections: intro + resolve
        intro_ms = int(total_duration_s * 0.5) * 1000
        resolve_ms = total_duration_s * 1000 - intro_ms
        return [
            {
                "sectionName": "Intro",
                "positiveLocalStyles": _section_styles(prompt, "sparse, gentle, single instrument, building slowly"),
                "negativeLocalStyles": ["loud", "complex", "full arrangement"],
                "durationMs": intro_ms,
                "lines": [],
            },
            {
                "sectionName": "Resolve",
                "positiveLocalStyles": _section_styles(prompt, "warmer, fuller, gentle resolution, soft landing"),
                "negativeLocalStyles": ["abrupt ending", "silence", "harsh"],
                "durationMs": resolve_ms + OVERSHOOT_MS,
                "lines": [],
            },
        ]

    # 3+ sections for longer pieces
    intro_ms = min(5000, int(total_duration_s * 0.25) * 1000)
    resolve_ms = min(5000, int(total_duration_s * 0.25) * 1000)
    body_ms = total_duration_s * 1000 - intro_ms - resolve_ms

    return [
        {
            "sectionName": "Intro",
            "positiveLocalStyles": _section_styles(prompt, "sparse, gentle opening, single instrument, quiet entry"),
            "negativeLocalStyles": ["loud", "complex arrangement", "full mix", "sudden entry"],
            "durationMs": intro_ms,
            "lines": [],
        },
        {
            "sectionName": "Body",
            "positiveLocalStyles": _section_styles(prompt, "developing theme, adding warmth, layered textures, emotional center"),
            "negativeLocalStyles": ["sparse", "sudden changes", "harsh transitions"],
            "durationMs": body_ms,
            "lines": [],
        },
        {
            "sectionName": "Resolve",
            "positiveLocalStyles": _section_styles(prompt, "gentle resolution, soft landing, warmth, hope, fading gracefully"),
            "negativeLocalStyles": ["abrupt ending", "silence", "new elements", "builds"],
            "durationMs": resolve_ms + OVERSHOOT_MS,
            "lines": [],
        },
    ]


def _section_styles(prompt: str, base_styles: str) -> list[str]:
    """Build local styles for a section from the prompt and base description."""
    styles = [s.strip() for s in base_styles.split(",")]
    # Add any specific descriptors from the prompt
    for token in [t.strip() for t in prompt.split(",") if t.strip()]:
        if token not in styles:
            styles.append(token)
    return styles


# ── ElevenLabs TTS ──────────────────────────────────────────────────────────


def build_tts_config(narration: dict) -> dict:
    """Build TTS adapter config from spec narration block.

    Requires either voice_id or voice design fields (voice_description,
    persona, emotion, delivery). No silent defaults — the concept must
    specify the voice.
    """
    config = dict(narration)

    if not config.get("voice_id"):
        has_design_fields = any(
            config.get(k) for k in ("voice_design_prompt", "voice_description", "persona", "emotion", "delivery")
        )
        if not has_design_fields:
            raise ValueError(
                "Narration missing voice specification. Provide 'voice_id' (from try-voice) "
                "or voice design fields ('voice_description', 'persona', 'emotion', 'delivery'). "
                "Every concept must define its own voice — there are no defaults."
            )

    return config
