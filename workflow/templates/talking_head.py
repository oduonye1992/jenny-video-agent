"""DAG template for talking head video production.

All video gen models (Sora, Kling, Veo) generate audio natively as part of
the video. No separate TTS or music steps needed — the prompt drives the
dialogue, tone, and background sound.

    image_gen(anchor) -> image_upscale(anchor) -> video_gen(shot_1) -> video_gen(shot_2) -> ... -> upscale(all) -> merge -> done
                                                        |                    |
                                                   extract_last_frame    extract_last_frame   (debugging artifacts)

Shots are sequential for frame chaining: the last frame of shot N becomes
the start frame of shot N+1 for character consistency. Each shot's last frame
is also extracted as a PNG for visual debugging. After all shots are generated,
each clip is upscaled in parallel, then merged.

The anchor frame is optionally upscaled via Magnific (image_upscale category)
for sharper source material before video generation. This single upscale
carries through all shots via frame chaining.
"""

from workflow.model_profiles import resolve_adapter
from workflow.prompt_builder import (
    build_character_ref_config,
    nano_banana_prompt_to_config,
    nano_banana_edit_to_config,
    scene_transfer_to_config,
    veo_prompt_to_config,
)
from workflow.templates.registry import register


@register("talking_head")
def compile(spec: dict) -> dict:
    """Compile a talking head production spec to pipeline JSON."""
    models = spec.get("models", {})
    character = spec.get("character", {})
    shots = spec.get("shots", [])
    output = spec.get("output", {})
    aspect_ratio = spec.get("aspect_ratio", "9:16")
    profile = spec.get("profile", "production")

    image_adapter = resolve_adapter(models, "image_gen", "talking_head", profile)
    image_upscale_adapter = resolve_adapter(models, "image_upscale", "talking_head", profile)
    video_adapter = resolve_adapter(models, "video_gen", "talking_head", profile)
    upscale_adapter = resolve_adapter(models, "upscale", "talking_head", profile)

    prop = spec.get("prop")

    nodes: list[dict] = []

    # Inspiration frame — passed as scene_reference to anchor image gen
    inspiration = spec.get("inspiration", {})
    inspiration_path = inspiration.get("frame_path") if inspiration.get("use_as_reference") else None

    # Step 1: Generate anchor frame from first shot's creative fields
    first_shot = shots[0] if shots else {}
    anchor_shot = _build_anchor_shot(first_shot, character, prop)
    is_ref_adapter = image_adapter in ("fal_nano_banana_edit", "fal_nano_banana_scene_transfer")
    if is_ref_adapter:
        if inspiration_path and not anchor_shot.get("reference_image") and not anchor_shot.get("reference_image_url"):
            anchor_shot["reference_image"] = inspiration_path
        if image_adapter == "fal_nano_banana_scene_transfer":
            # Scene transfer: changes prompt is built from subject/wardrobe only
            # Lighting, camera, setting come from the reference via Gemini
            image_config = {
                "output_filename": "anchor_frame.png",
                **scene_transfer_to_config(anchor_shot, spec),
                **{k: v for k, v in models.get("image_gen", {}).items() if k not in ("adapter", "fallback")},
            }
        else:
            # Edit adapter: flat prompt with everything (direct pass-through)
            if not anchor_shot.get("image_prompt") and character:
                parts = []
                if character.get("description"):
                    parts.append(character["description"])
                if anchor_shot.get("scene"):
                    parts.append(anchor_shot["scene"])
                if anchor_shot.get("wardrobe_top"):
                    parts.append(f"Wearing {anchor_shot['wardrobe_top']}.")
                if anchor_shot.get("action"):
                    parts.append(anchor_shot["action"])
                anchor_shot["image_prompt"] = " ".join(parts)
            image_config = {
                "output_filename": "anchor_frame.png",
                **nano_banana_edit_to_config(anchor_shot, spec),
                **{k: v for k, v in models.get("image_gen", {}).items() if k not in ("adapter", "fallback")},
            }
    else:
        image_config = {
            "output_filename": "anchor_frame.png",
            **nano_banana_prompt_to_config(anchor_shot, spec),
            **{k: v for k, v in models.get("image_gen", {}).items() if k not in ("adapter", "fallback")},
        }
        if inspiration_path:
            image_config["scene_reference"] = inspiration_path

    nodes.append({
        "id": "image_gen.anchor",
        "adapter": image_adapter,
        "config": image_config,
        "depends_on": [],
    })

    # Step 1.5: Optionally upscale anchor frame (Magnific) for sharper source
    anchor_output_step = "image_gen.anchor"
    if image_upscale_adapter:
        # Build a guidance prompt from the anchor's creative fields so Magnific
        # knows what to enhance (skin texture, lighting quality, fabric detail).
        upscale_prompt = _build_upscale_prompt(anchor_shot, character)
        upscale_config = {
            "image_from": "image_gen.anchor",
            "output_filename": "anchor_frame_upscaled.png",
            "scale_factor": "2x",
            "optimized_for": "soft_portraits",
            "creativity": -3,
            "resemblance": 3,
            **{k: v for k, v in models.get("image_upscale", {}).items() if k not in ("adapter", "fallback")},
        }
        if upscale_prompt:
            upscale_config["prompt"] = upscale_prompt
        nodes.append({
            "id": "image_upscale.anchor",
            "adapter": image_upscale_adapter,
            "config": upscale_config,
            "depends_on": ["image_gen.anchor"],
        })
        anchor_output_step = "image_upscale.anchor"

    # Step 2+: Generate each shot sequentially (frame chaining)
    prev_step = anchor_output_step
    video_step_ids = []

    char_ref_config = build_character_ref_config(spec, video_adapter, fallback_frame_from=anchor_output_step)

    for i, shot in enumerate(shots):
        step_id = f"video_gen.shot_{i + 1}"
        video_config = {
            "start_frame_from": prev_step,
            "duration": shot.get("duration", 8),
            "aspect_ratio": aspect_ratio,
            "output_filename": f"shot_{i + 1}.mp4",
            **veo_prompt_to_config(shot, spec),
            **char_ref_config,
            **{k: v for k, v in models.get("video_gen", {}).items() if k not in ("adapter", "fallback")},
        }
        nodes.append({
            "id": step_id,
            "adapter": video_adapter,
            "config": video_config,
            "depends_on": [prev_step],
        })
        video_step_ids.append(step_id)

        # Extract last frame — used for frame chaining to the next shot.
        extract_step_id = f"extract_last_frame.shot_{i + 1}"
        nodes.append({
            "id": extract_step_id,
            "adapter": "ffmpeg_extract_last_frame",
            "config": {
                "video_from": step_id,
                "output_filename": f"shot_{i + 1}_last_frame.png",
            },
            "depends_on": [step_id],
        })

        # Next shot chains off the extracted frame, not the raw video
        prev_step = extract_step_id

    # Step 3: Upscale each clip (parallel, after all shots complete)
    pre_merge_step_ids = []
    if upscale_adapter:
        for i in range(len(shots)):
            video_step_id = video_step_ids[i]
            upscale_step_id = f"upscale.shot_{i + 1}"
            nodes.append({
                "id": upscale_step_id,
                "adapter": upscale_adapter,
                "config": {
                    "video_from": video_step_id,
                    "output_filename": f"shot_{i + 1}_upscaled.mp4",
                    "aspect_ratio": aspect_ratio,
                },
                "depends_on": [video_step_id],
            })
            pre_merge_step_ids.append(upscale_step_id)
    else:
        pre_merge_step_ids = video_step_ids

    final_filename = output.get("final_filename", "final.mp4")

    # Final step: merge all shots (skip if single shot)
    if len(pre_merge_step_ids) == 1:
        # Single shot — rename output directly in the video config
        for node in nodes:
            if node["id"] == pre_merge_step_ids[0]:
                node["config"]["output_filename"] = final_filename
                break
    else:
        nodes.append({
            "id": "merge_videos",
            "adapter": "ffmpeg_concat",
            "config": {
                "clips_from": pre_merge_step_ids,
                "include_audio": True,
                "output_filename": final_filename,
            },
            "depends_on": pre_merge_step_ids,
        })

    return {"pipeline_version": 1, "nodes": nodes}




def _build_upscale_prompt(anchor_shot: dict, character: dict) -> str:
    """Build a guidance prompt for Magnific from the anchor's creative fields.

    Tells Magnific what's in the image so it enhances the right details —
    skin texture, fabric weave, hair strands, lighting quality.
    """
    parts = []
    if character.get("description"):
        parts.append(character["description"])
    if anchor_shot.get("scene"):
        parts.append(anchor_shot["scene"])
    if anchor_shot.get("lighting"):
        parts.append(anchor_shot["lighting"])
    if anchor_shot.get("camera"):
        parts.append(anchor_shot["camera"])
    if anchor_shot.get("wardrobe_top"):
        parts.append(f"Wearing {anchor_shot['wardrobe_top']}.")
    return " ".join(parts)


def _build_anchor_shot(first_shot: dict, character: dict, prop: dict | None = None) -> dict:
    """Build a synthetic shot dict for the anchor frame image generation.

    Merges character info and prop into the first shot's creative fields so the
    prompt builder can generate a full Nano Banana spec for the anchor frame.
    """
    anchor = dict(first_shot)

    # Add prop to props field
    if prop:
        prop_desc = prop.get("description", "")
        held = prop.get("held_by", "")
        prop_text = prop_desc
        if held:
            prop_text += f", {held}"
        existing_props = anchor.get("props", "")
        if existing_props:
            anchor["props"] = f"{existing_props}, {prop_text}"
        else:
            anchor["props"] = prop_text

    # Default camera for talking head anchor if not specified
    if not anchor.get("camera"):
        anchor["camera"] = (
            "Selfie POV, front-facing phone camera held at arm's length, "
            "slightly above eye level, natural handheld micro-movement. "
            "Wide-angle 24mm equivalent, deep focus, close proximity to face."
        )

    # Remove action for a still anchor frame
    anchor.pop("action", None)
    anchor["action"] = "Holding phone at arm's length, looking directly into front camera, natural relaxed expression, ready to speak."

    return anchor
