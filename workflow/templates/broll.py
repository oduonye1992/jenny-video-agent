"""B-roll DAG template.

Builds the following execution graph from a production spec:

                                              +-> tts(narration) ---------------+
                                              |                                 |
image_gen(shot_1) -> video_gen(shot_1) -> upscale(shot_1) +                     |
image_gen(shot_2) -> video_gen(shot_2) -> upscale(shot_2) +-> merge --> mix --> done
image_gen(shot_3) -> video_gen(shot_3) -> upscale(shot_3) +                     |
                                              |                                 |
                                              +-> music(mood) ------------------+

All image_gen steps run in parallel (no deps).
Each video_gen step depends on its own image_gen step.
Each upscale step depends on its own video_gen step.
TTS and music run in parallel with everything (no deps).
merge_videos depends on all upscale steps (or video_gen if upscale disabled).
mix_audio depends on merge_videos + tts + music.
"""

from workflow.model_profiles import resolve_adapter
from workflow.prompt_builder import (
    build_character_ref_config,
    nano_banana_prompt_to_config,
    nano_banana_edit_to_config,
    scene_transfer_to_config,
    veo_prompt_to_config,
    build_tts_config,
    build_music_config,
)
from workflow.templates.registry import register


@register("broll")
def compile(spec: dict) -> dict:
    """Compile a b-roll production spec to pipeline JSON."""
    models = spec.get("models", {})
    shots = spec.get("shots", [])
    output_cfg = spec.get("output", {})
    character = spec.get("character")
    profile = spec.get("profile", "production")

    # Adapter names: spec overrides profile defaults
    image_adapter = resolve_adapter(models, "image_gen", "broll", profile)
    video_adapter = resolve_adapter(models, "video_gen", "broll", profile)
    upscale_adapter = resolve_adapter(models, "upscale", "broll", profile)
    tts_adapter = resolve_adapter(models, "tts", "broll", profile)
    music_adapter = resolve_adapter(models, "music", "broll", profile)

    nodes: list[dict] = []
    # The step IDs that feed into merge (upscale if enabled, else video_gen)
    pre_merge_step_ids: list[str] = []

    # Inspiration frame — passed as scene_reference to image gen for style consistency
    inspiration = spec.get("inspiration", {})
    inspiration_path = inspiration.get("frame_path") if inspiration.get("use_as_reference") else None

    # Build character reference config once (same for all shots).
    first_shot_id = shots[0].get("shot_id", "shot_1") if shots else "shot_1"
    first_image_step_id = f"image_gen_{first_shot_id}"
    char_ref_config = build_character_ref_config(spec, video_adapter, fallback_frame_from=first_image_step_id)

    # ── Per-shot steps: image_gen -> video_gen -> upscale ─────────────────

    for i, shot in enumerate(shots):
        shot_id = shot.get("shot_id", f"shot_{i + 1}")
        image_step_id = f"image_gen_{shot_id}"
        video_step_id = f"video_gen_{shot_id}"

        # ── Image generation (no dependencies — runs in parallel) ──────

        is_ref_adapter = image_adapter in ("fal_nano_banana_edit", "fal_nano_banana_scene_transfer")
        if is_ref_adapter:
            if inspiration_path and not shot.get("reference_image") and not shot.get("reference_image_url"):
                shot["reference_image"] = inspiration_path
            if image_adapter == "fal_nano_banana_scene_transfer":
                # Scene transfer: changes prompt is built from subject/wardrobe only
                # Lighting, camera, setting come from the reference via Gemini
                image_config = {
                    "output_filename": f"{shot_id}_frame.png",
                    **scene_transfer_to_config(shot, spec),
                    **{k: v for k, v in models.get("image_gen", {}).items() if k not in ("adapter", "fallback")},
                }
            else:
                # Edit adapter: flat prompt with everything (direct pass-through)
                if not shot.get("image_prompt") and character:
                    parts = []
                    if character.get("description"):
                        parts.append(character["description"])
                    if shot.get("scene"):
                        parts.append(shot["scene"])
                    if shot.get("wardrobe_top"):
                        parts.append(f"Wearing {shot['wardrobe_top']}.")
                    if shot.get("action"):
                        parts.append(shot["action"])
                    shot["image_prompt"] = " ".join(parts)
                image_config = {
                    "output_filename": f"{shot_id}_frame.png",
                    **nano_banana_edit_to_config(shot, spec),
                    **{k: v for k, v in models.get("image_gen", {}).items() if k not in ("adapter", "fallback")},
                }
        else:
            image_config = {
                "output_filename": f"{shot_id}_frame.png",
                **nano_banana_prompt_to_config(shot, spec),
                **{k: v for k, v in models.get("image_gen", {}).items() if k not in ("adapter", "fallback")},
            }
            if inspiration_path:
                image_config["scene_reference"] = inspiration_path

        nodes.append({
            "id": image_step_id,
            "adapter": image_adapter,
            "config": image_config,
            "depends_on": [],
        })

        # ── Video generation (depends on its own image_gen) ────────────

        video_config = {
            "start_frame_from": image_step_id,
            "output_filename": f"{shot_id}_video.mp4",
            "duration": shot.get("duration", 8),
            "aspect_ratio": shot.get("aspect_ratio", spec.get("aspect_ratio", "9:16")),
            **veo_prompt_to_config(shot, spec),
            **char_ref_config,
            **{k: v for k, v in models.get("video_gen", {}).items() if k not in ("adapter", "fallback")},
        }
        nodes.append({
            "id": video_step_id,
            "adapter": video_adapter,
            "config": video_config,
            "depends_on": [image_step_id],
        })

        # Upscale (depends on video_gen, feeds into merge)
        if upscale_adapter:
            upscale_step_id = f"upscale_{shot_id}"
            aspect_ratio = shot.get("aspect_ratio", spec.get("aspect_ratio", "9:16"))
            nodes.append({
                "id": upscale_step_id,
                "adapter": upscale_adapter,
                "config": {
                    "video_from": video_step_id,
                    "output_filename": f"{shot_id}_upscaled.mp4",
                    "aspect_ratio": aspect_ratio,
                },
                "depends_on": [video_step_id],
            })
            pre_merge_step_ids.append(upscale_step_id)
        else:
            pre_merge_step_ids.append(video_step_id)

    # ── TTS step (no dependencies — parallel with everything) ─────────────

    narration_cfg = spec.get("narration", {})
    tts_step_id = "tts"
    tts_config = build_tts_config(narration_cfg)
    tts_config["output_filename"] = "narration.mp3"
    tts_config.update({k: v for k, v in models.get("tts", {}).items() if k not in ("adapter", "fallback")})
    nodes.append({
        "id": tts_step_id,
        "adapter": tts_adapter,
        "config": tts_config,
        "depends_on": [],
    })

    # ── Music step (no dependencies — parallel with everything) ───────────

    music_cfg = spec.get("music", {})
    music_step_id = "music"
    total_duration_s = sum(shot.get("duration", 8) for shot in shots)
    music_config = build_music_config(music_cfg, total_duration_s)
    music_config["output_filename"] = "music.mp3"
    if "sections" not in music_config:
        music_config.setdefault("music_length_ms", total_duration_s * 1000)
    music_config.update({k: v for k, v in models.get("music", {}).items() if k not in ("adapter", "fallback")})
    nodes.append({
        "id": music_step_id,
        "adapter": music_adapter,
        "config": music_config,
        "depends_on": [],
    })

    # ── Merge videos (depends on all upscale/video_gen steps) ────────────

    merge_cfg = spec.get("merge", {})
    mix_cfg = spec.get("mix", {})
    final_filename = output_cfg.get("final_filename", "final.mp4")

    if len(pre_merge_step_ids) == 1:
        # Single shot — skip concat, mix_audio takes the clip directly
        mix_depends = [pre_merge_step_ids[0], tts_step_id, music_step_id]
        video_from = pre_merge_step_ids[0]
    else:
        # Multiple shots — concat then mix
        merge_step_id = "merge_videos"
        nodes.append({
            "id": merge_step_id,
            "adapter": "ffmpeg_concat",
            "config": {
                "clips_from": pre_merge_step_ids,
                "output_filename": "merged.mp4",
                **({"resolution": merge_cfg["resolution"]} if "resolution" in merge_cfg else {}),
            },
            "depends_on": pre_merge_step_ids,
        })
        mix_depends = [merge_step_id, tts_step_id, music_step_id]
        video_from = merge_step_id

    # ── Mix audio ────────────────────────────────────────────────────────

    nodes.append({
        "id": "mix_audio",
        "adapter": "ffmpeg_mix_audio",
        "config": {
            "video_from": video_from,
            "narration_from": tts_step_id,
            "music_from": music_step_id,
            "music_volume_db": mix_cfg.get("music_volume_db", -12),
            "output_filename": final_filename,
        },
        "depends_on": mix_depends,
    })

    return {"pipeline_version": 1, "nodes": nodes}


