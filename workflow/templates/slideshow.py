"""DAG template for slideshow video production.

With AI backgrounds (default):
    nano_banana(bg_1) → pil_render(slide_1) -+
    nano_banana(bg_2) → pil_render(slide_2) -+→ assemble_slideshow → done
    nano_banana(bg_3) → pil_render(slide_3) -+
    music(mood) ----------------------------+

Without AI backgrounds (gradient fallback):
    pil_render(slide_1) -+
    pil_render(slide_2) -+→ assemble_slideshow → done
    pil_render(slide_3) -+
    music(mood) ---------+

Background generation and music run in parallel.
Each pil_render step depends on its corresponding background step.
The assemble step depends on all pil_render steps + music.
"""

from workflow.model_profiles import resolve_adapter
from workflow.templates.registry import register


def _build_bg_prompt(slide: dict, spec: dict) -> str:
    """Build a Nano Banana prompt for an atmospheric slide background.

    Generates abstract/moody backgrounds that work well with text overlay.
    The prompt emphasizes atmosphere, lighting, and texture — never text or people.
    """
    mood = slide.get("bg_mood", "")
    style = slide.get("style", "dark")

    style_moods = {
        "dark": "dark moody atmosphere, deep shadows, subtle warm light",
        "dark_warm": "warm amber tones, soft golden light, dark cozy atmosphere",
        "dark_cool": "cool blue tones, soft moonlight, serene dark atmosphere",
        "midnight": "deep purple twilight, soft ethereal glow, dreamy dark atmosphere",
        "minimal": "soft neutral tones, gentle natural light, clean minimalist space",
    }
    base_mood = style_moods.get(style, style_moods["dark"])
    atmosphere = mood if mood else base_mood

    bg_style = spec.get("background_style", "abstract atmospheric, soft bokeh, cinematic lighting")

    return (
        f"{bg_style}, {atmosphere}, "
        "no text, no words, no letters, no people, no faces, "
        "subtle texture, depth of field, 8k quality"
    )


@register("slideshow")
def compile(spec: dict) -> dict:
    """Compile a slideshow production spec to pipeline JSON."""
    models = spec.get("models", {})
    slides = spec.get("slides", [])
    output = spec.get("output", {})
    music_spec = spec.get("music", {})
    aspect_ratio = spec.get("aspect_ratio", "9:16")
    profile = spec.get("profile", "production")

    music_adapter = resolve_adapter(models, "music", "slideshow", profile)

    # Check if AI backgrounds are requested (image_gen model specified)
    has_image_gen = "image_gen" in models
    if has_image_gen:
        image_adapter = resolve_adapter(models, "image_gen", "slideshow", profile)

    nodes: list[dict] = []

    # Render each slide
    slide_step_ids = []
    total_slides = len(slides)
    for i, slide in enumerate(slides):
        slide_type = slide.get("type", "text")
        pil_type = "cta" if slide_type == "cta" else "content"
        bg_deps = []

        # Step 1: Generate AI background (if enabled)
        bg_step_id = None
        if has_image_gen and slide.get("bg_enabled", True):
            bg_step_id = f"image_gen.bg_{i + 1}"
            bg_prompt = slide.get("bg_prompt", _build_bg_prompt(slide, spec))

            nodes.append({
                "id": bg_step_id,
                "adapter": image_adapter,
                "config": {
                    "prompt": bg_prompt,
                    "negative_prompt": "text, words, letters, writing, numbers, people, faces, hands",
                    "aspect_ratio": aspect_ratio,
                    "resolution": "1K",
                    "output_filename": f"bg_{i + 1}.png",
                },
                "depends_on": [],
            })
            bg_deps = [bg_step_id]

        # Step 2: Render text on top (depends on background if AI-generated)
        step_id = f"pil_render.slide_{i + 1}"
        config = {
            "type": pil_type,
            "headline": slide.get("headline", ""),
            "body": slide.get("body", ""),
            "style": slide.get("style", "dark"),
            "accent_words": slide.get("accent_words", []),
            "aspect_ratio": aspect_ratio,
            "output_filename": f"slide_{i + 1}.png",
        }
        if bg_step_id:
            config["background_from"] = bg_step_id
            config["overlay_opacity"] = slide.get("overlay_opacity", 0.55)
        if pil_type == "cta":
            config["cta_text"] = slide.get("headline", "")

        nodes.append({
            "id": step_id,
            "adapter": "pil_render",
            "config": config,
            "depends_on": bg_deps,
        })
        slide_step_ids.append(step_id)

    # Music generation (parallel with everything above)
    total_duration_s = sum(s.get("duration", 4) for s in slides)
    nodes.append({
        "id": "music",
        "adapter": music_adapter,
        "config": {
            "prompt": music_spec.get("mood", ""),
            **({"composition_plan": music_spec["composition_plan"]} if music_spec.get("composition_plan") else {}),
            "music_length_ms": int(total_duration_s * 1000),
            "output_filename": "music.mp3",
        },
        "depends_on": [],
    })

    # Assemble slideshow: depends on all pil_render steps + music
    all_deps = slide_step_ids + ["music"]
    nodes.append({
        "id": "assemble_slideshow",
        "adapter": "local_ffmpeg",
        "config": {
            "operation": "slideshow",
            "slides_from": slide_step_ids,
            "music_from": "music",
            "slide_durations": [s.get("duration", 4) for s in slides],
            "music_volume_db": music_spec.get("volume_db", -8),
            "transition": spec.get("transition", "crossfade"),
            "transition_duration": spec.get("transition_duration", 0.5),
            "output_filename": output.get("final_filename", "final.mp4"),
        },
        "depends_on": all_deps,
    })

    return {"pipeline_version": 1, "nodes": nodes}
