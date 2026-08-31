"""Unified video DAG template.

A video is an ordered list of shots. Each shot is self-contained — its own
character, scene, dialogue, duration. Like a CapCut timeline: drop in whatever
clips you want and the final video is those clips concatenated in order.

Four shot relationship types:

1. Pre-generated (shot.start_frame) — frame already exists, skip image_gen:

    video_gen(shot_1) -> [upscale(shot_1)] ─┐
    video_gen(shot_2) -> [upscale(shot_2)] ─┼─> merge -> done

    Fastest — no image generation cost. Used after try-frame / seed bracket.

2. Independent (default) — own image_gen, runs in parallel:

    image_gen(shot_1) -> video_gen(shot_1) -> [upscale(shot_1)] ─┐
    image_gen(shot_2) -> video_gen(shot_2) -> [upscale(shot_2)] ─┼─> merge -> done
    image_gen(shot_3) -> video_gen(shot_3) -> [upscale(shot_3)] ─┘

3. Derived (shot.derive_from) — nano edit variation of another shot's frame:

    [anchor frame] ─────────────────────-> video_gen(shot_1) ─┐
           │                                                  │
           ├─> image_edit(shot_2) -> video_gen(shot_2) ───────┼─> merge
           └─> image_edit(shot_3) -> video_gen(shot_3) ───────┘

    Anchor can be start_frame (static) or image_gen (dynamic).
    Edits fan out in parallel, videos in parallel.

4. Chained (shot.chain_from) — sequential, inherits last video frame:

    image_gen(shot_1) -> video_gen(shot_1) -> extract_last_frame(shot_1)
                                                        │
                                              video_gen(shot_2) -> ...

With optional audio overlay (narration and/or music):

    [visual pipeline] ──> merge ─┐
                   [tts] ────────┼─> mix_audio -> done
                   [music] ──────┘

TTS and music run in parallel with everything (no deps).
merge depends on all final video steps.
mix_audio depends on merge + tts + music (only if audio layers exist).
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


def _build_negative_prompt(shot: dict, existing: str | None = None) -> str:
    """Build negative prompt to enforce audio and composition rules.

    - Talking head shots (dialogue detected): block ambient/background audio.
    - Static shots: block zoom, pan, camera movement.
    """
    parts = []
    if existing:
        parts.append(existing)

    prompt = shot.get("video_prompt", "")

    # Block ambient audio when dialogue is present
    if "says:" in prompt.lower() or "dialogue:" in prompt.lower():
        parts.append(
            "No background sounds, no ambient noise, no room tone, "
            "no environmental audio, no wind, no hum, no rustling"
        )

    # Lock composition for static shots
    if "static" in prompt.lower() or "locked off" in prompt.lower():
        parts.append(
            "No zoom, no camera movement, no reframing, no dolly, no pan, no tilt"
        )

    return ". ".join(parts) if parts else ""


@register("video")
def compile(spec: dict) -> dict:
    """Compile a unified video production spec to pipeline JSON."""
    models = spec.get("models", {})
    shots = spec.get("shots", [])
    output_cfg = spec.get("output", {})
    character = spec.get("character")
    profile = spec.get("profile", "production")

    # Adapter names: spec overrides profile defaults
    image_adapter = resolve_adapter(models, "image_gen", "video", profile)
    video_adapter = resolve_adapter(models, "video_gen", "video", profile)
    upscale_adapter = resolve_adapter(models, "upscale", "video", profile)

    nodes: list[dict] = []
    # Step IDs that feed into merge (upscale if enabled, else video_gen)
    pre_merge_step_ids: list[str] = []
    # Map shot_id -> extract_last_frame step_id (for chain_from resolution)
    extract_step_map: dict[str, str] = {}
    # Map shot_id -> image_gen step_id OR static path (for derive_from resolution)
    # Values starting with "/" or containing "." are static paths (start_frame);
    # all others are step IDs resolved by the engine at runtime.
    image_gen_step_map: dict[str, str] = {}
    # Track which entries are static paths vs step IDs
    static_frame_map: dict[str, str] = {}  # shot_id -> file path

    # Inspiration frame — passed as scene_reference to image gen for style consistency
    inspiration = spec.get("inspiration", {})
    inspiration_path = inspiration.get("frame_path") if inspiration.get("use_as_reference") else None

    # Build character reference config once (same for all shots that share the spec-level character).
    first_shot_id = shots[0].get("shot_id", "shot_1") if shots else "shot_1"
    first_image_step_id = f"image_gen_{first_shot_id}"
    char_ref_config = build_character_ref_config(spec, video_adapter, fallback_frame_from=first_image_step_id)

    # ── Pre-scan: which shots are chain_from targets? ───────────────────
    chain_targets: set[str] = set()
    for shot in shots:
        cf = shot.get("chain_from")
        if cf:
            chain_targets.add(cf)

    # ── Per-shot steps ─────────────────────────────────────────────────────

    for i, shot in enumerate(shots):
        shot_id = shot.get("shot_id", f"shot_{i + 1}")
        image_step_id = f"image_gen_{shot_id}"
        video_step_id = f"video_gen_{shot_id}"

        # Check shot relationship type: start_frame, chain_from, derive_from, or independent
        start_frame = shot.get("start_frame")
        chain_from = shot.get("chain_from")
        derive_from = shot.get("derive_from")

        if start_frame:
            # ── Pre-generated frame: skip image_gen, go straight to video ──
            # The frame already exists on disk (from try-frame, seed bracket, etc.)
            # Register in maps so derived shots can reference it.
            image_gen_step_map[shot_id] = shot_id  # placeholder key
            static_frame_map[shot_id] = start_frame

            neg = _build_negative_prompt(shot, shot.get("negative_prompt"))
            video_config = {
                "start_frame_path": start_frame,
                "output_filename": f"{shot_id}_video.mp4",
                "duration": shot.get("duration", 8),
                "aspect_ratio": shot.get("aspect_ratio", spec.get("aspect_ratio", "9:16")),
                **veo_prompt_to_config(shot, spec),
                **char_ref_config,
                **{k: v for k, v in models.get("video_gen", {}).items() if k not in ("adapter", "fallback")},
                **({"negative_prompt": neg} if neg else {}),
            }
            nodes.append({
                "id": video_step_id,
                "adapter": video_adapter,
                "config": video_config,
                "depends_on": [],
            })

        elif chain_from:
            # ── Chained shot: sequential, inherits last video frame ──
            chain_step_id = extract_step_map.get(chain_from)
            if not chain_step_id:
                raise ValueError(
                    f"Shot '{shot_id}' has chain_from='{chain_from}' but that shot "
                    f"hasn't been defined yet or doesn't exist. Chained shots must "
                    f"appear after the shot they chain from."
                )

            neg = _build_negative_prompt(shot, shot.get("negative_prompt"))
            video_config = {
                "start_frame_from": chain_step_id,
                "output_filename": f"{shot_id}_video.mp4",
                "duration": shot.get("duration", 8),
                "aspect_ratio": shot.get("aspect_ratio", spec.get("aspect_ratio", "9:16")),
                **veo_prompt_to_config(shot, spec),
                **char_ref_config,
                **{k: v for k, v in models.get("video_gen", {}).items() if k not in ("adapter", "fallback")},
                **({"negative_prompt": neg} if neg else {}),
            }
            nodes.append({
                "id": video_step_id,
                "adapter": video_adapter,
                "config": video_config,
                "depends_on": [chain_step_id],
            })

        elif derive_from:
            # ── Derived shot: nano edit variation of another shot's frame ──
            # The source shot can be a generated frame (step ID) or a
            # pre-existing frame (start_frame path). Both produce the same
            # edit step — the only difference is the dependency and how the
            # reference image is resolved.
            if derive_from not in image_gen_step_map:
                raise ValueError(
                    f"Shot '{shot_id}' has derive_from='{derive_from}' but that shot "
                    f"hasn't been defined yet or doesn't have a frame. "
                    f"Derived shots must appear after the shot they derive from, "
                    f"and the source shot must be independent or have a start_frame."
                )

            # Build the edit prompt from image_prompt or structured fields
            edit_prompt = shot.get("image_prompt", "")
            if not edit_prompt and character:
                parts = []
                if character.get("description"):
                    parts.append(character["description"])
                if shot.get("scene"):
                    parts.append(shot["scene"])
                if shot.get("camera"):
                    parts.append(shot["camera"])
                if shot.get("wardrobe_top"):
                    parts.append(f"Wearing {shot['wardrobe_top']}.")
                if shot.get("action"):
                    parts.append(shot["action"])
                edit_prompt = " ".join(parts)

            if not edit_prompt:
                raise ValueError(
                    f"Shot '{shot_id}' derives from '{derive_from}' but has no "
                    f"'image_prompt' describing what to change. Provide the delta "
                    f"(e.g. 'Pull back to medium shot, hands mid-gesture')."
                )

            edit_step_id = f"image_edit_{shot_id}"
            edit_config = {
                "prompt": edit_prompt,
                "output_filename": f"{shot_id}_frame.png",
                "aspect_ratio": shot.get("aspect_ratio", spec.get("aspect_ratio", "9:16")),
            }

            # Resolve the anchor: static path (start_frame) or step reference
            anchor_static_path = static_frame_map.get(derive_from)
            if anchor_static_path:
                # Anchor is a pre-existing file — pass path directly, no deps
                edit_config["reference_image"] = anchor_static_path
                edit_depends = []
            else:
                # Anchor is a generated frame — use _from ref, depend on the step
                anchor_image_step = image_gen_step_map[derive_from]
                edit_config["reference_image_from"] = anchor_image_step
                edit_depends = [anchor_image_step]

            # Pass through any image_gen model overrides
            edit_config.update({
                k: v for k, v in models.get("image_gen", {}).items()
                if k not in ("adapter", "fallback")
            })

            nodes.append({
                "id": edit_step_id,
                "adapter": "fal_nano_banana_edit",
                "config": edit_config,
                "depends_on": edit_depends,
            })

            # Video generation depends on the edit step
            neg = _build_negative_prompt(shot, shot.get("negative_prompt"))
            video_config = {
                "start_frame_from": edit_step_id,
                "output_filename": f"{shot_id}_video.mp4",
                "duration": shot.get("duration", 8),
                "aspect_ratio": shot.get("aspect_ratio", spec.get("aspect_ratio", "9:16")),
                **veo_prompt_to_config(shot, spec),
                **char_ref_config,
                **{k: v for k, v in models.get("video_gen", {}).items() if k not in ("adapter", "fallback")},
                **({"negative_prompt": neg} if neg else {}),
            }
            nodes.append({
                "id": video_step_id,
                "adapter": video_adapter,
                "config": video_config,
                "depends_on": [edit_step_id],
            })

        else:
            # ── Independent shot: own image_gen, runs in parallel ────

            # ── Image generation (no deps — runs in parallel) ────────
            is_ref_adapter = image_adapter in ("fal_nano_banana_edit", "fal_nano_banana_scene_transfer")
            if is_ref_adapter:
                if inspiration_path and not shot.get("reference_image") and not shot.get("reference_image_url"):
                    shot["reference_image"] = inspiration_path
                if image_adapter == "fal_nano_banana_scene_transfer":
                    image_config = {
                        "output_filename": f"{shot_id}_frame.png",
                        **scene_transfer_to_config(shot, spec),
                        **{k: v for k, v in models.get("image_gen", {}).items() if k not in ("adapter", "fallback")},
                    }
                else:
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
            image_gen_step_map[shot_id] = image_step_id

            # ── Video generation (depends on its own image_gen) ──────
            neg = _build_negative_prompt(shot, shot.get("negative_prompt"))
            video_config = {
                "start_frame_from": image_step_id,
                "output_filename": f"{shot_id}_video.mp4",
                "duration": shot.get("duration", 8),
                "aspect_ratio": shot.get("aspect_ratio", spec.get("aspect_ratio", "9:16")),
                **veo_prompt_to_config(shot, spec),
                **char_ref_config,
                **{k: v for k, v in models.get("video_gen", {}).items() if k not in ("adapter", "fallback")},
                **({"negative_prompt": neg} if neg else {}),
            }
            nodes.append({
                "id": video_step_id,
                "adapter": video_adapter,
                "config": video_config,
                "depends_on": [image_step_id],
            })

        # Extract last frame — only when another shot chains from this one
        if shot_id in chain_targets:
            extract_step_id = f"extract_last_frame_{shot_id}"
            nodes.append({
                "id": extract_step_id,
                "adapter": "ffmpeg_extract_last_frame",
                "config": {
                    "video_from": video_step_id,
                    "output_filename": f"{shot_id}_last_frame.png",
                },
                "depends_on": [video_step_id],
            })
            extract_step_map[shot_id] = extract_step_id

        # Upscale (depends on video_gen, feeds into merge)
        if upscale_adapter:
            upscale_step_id = f"upscale_{shot_id}"
            nodes.append({
                "id": upscale_step_id,
                "adapter": upscale_adapter,
                "config": {
                    "video_from": video_step_id,
                    "output_filename": f"{shot_id}_upscaled.mp4",
                    "aspect_ratio": shot.get("aspect_ratio", spec.get("aspect_ratio", "9:16")),
                },
                "depends_on": [video_step_id],
            })
            pre_merge_step_ids.append(upscale_step_id)
        else:
            pre_merge_step_ids.append(video_step_id)

    # ── Determine audio layers ─────────────────────────────────────────────

    narration_cfg = spec.get("narration")
    music_cfg = spec.get("music")
    has_narration = narration_cfg and isinstance(narration_cfg, dict) and narration_cfg.get("script")
    has_music = music_cfg and isinstance(music_cfg, dict) and (music_cfg.get("mood") or music_cfg.get("composition_plan"))

    tts_step_id = None
    music_step_id = None

    if has_narration:
        tts_adapter = resolve_adapter(models, "tts", "video", profile)
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

    if has_music:
        music_adapter = resolve_adapter(models, "music", "video", profile)
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

    # ── Merge videos ───────────────────────────────────────────────────────

    merge_cfg = spec.get("merge", {})
    mix_cfg = spec.get("mix", {})
    final_filename = output_cfg.get("final_filename", "final.mp4")
    needs_audio_mix = has_narration or has_music

    if len(pre_merge_step_ids) == 1 and not needs_audio_mix:
        # Single shot, no audio overlay — just rename the output
        for node in nodes:
            if node["id"] == pre_merge_step_ids[0]:
                node["config"]["output_filename"] = final_filename
                break
    elif len(pre_merge_step_ids) == 1 and needs_audio_mix:
        # Single shot with audio overlay — skip concat, go straight to mix
        video_from = pre_merge_step_ids[0]
        mix_depends = [video_from]
        mix_config: dict = {
            "video_from": video_from,
            "output_filename": final_filename,
        }
        if tts_step_id:
            mix_depends.append(tts_step_id)
            mix_config["narration_from"] = tts_step_id
        if music_step_id:
            mix_depends.append(music_step_id)
            mix_config["music_from"] = music_step_id
            mix_config["music_volume_db"] = mix_cfg.get("music_volume_db", -12)
        nodes.append({
            "id": "mix_audio",
            "adapter": "ffmpeg_mix_audio",
            "config": mix_config,
            "depends_on": mix_depends,
        })
    else:
        # Multiple shots — concat first
        merge_step_id = "merge_videos"
        # Include native audio in concat (talking head clips have dialogue)
        nodes.append({
            "id": merge_step_id,
            "adapter": "ffmpeg_concat",
            "config": {
                "clips_from": pre_merge_step_ids,
                "include_audio": True,
                "output_filename": "merged.mp4" if needs_audio_mix else final_filename,
                **({"resolution": merge_cfg["resolution"]} if "resolution" in merge_cfg else {}),
            },
            "depends_on": pre_merge_step_ids,
        })

        if needs_audio_mix:
            # Mix narration/music on top of the merged video
            mix_depends = [merge_step_id]
            mix_config = {
                "video_from": merge_step_id,
                "output_filename": final_filename,
            }
            if tts_step_id:
                mix_depends.append(tts_step_id)
                mix_config["narration_from"] = tts_step_id
            if music_step_id:
                mix_depends.append(music_step_id)
                mix_config["music_from"] = music_step_id
                mix_config["music_volume_db"] = mix_cfg.get("music_volume_db", -12)
            nodes.append({
                "id": "mix_audio",
                "adapter": "ffmpeg_mix_audio",
                "config": mix_config,
                "depends_on": mix_depends,
            })

    return {"pipeline_version": 1, "nodes": nodes}
