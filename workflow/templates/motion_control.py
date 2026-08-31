"""DAG template for motion control video production.

    download_clip -> extract_frame -> image_gen(character_frame) -> video_gen(motion_control) -> done

Downloads a reference clip, extracts a frame, generates a character replacement
frame, then runs motion-controlled video generation.
"""

from workflow.templates.registry import register


@register("motion_control")
def compile(spec: dict) -> dict:
    """Compile a motion control production spec to pipeline JSON."""
    models = spec.get("models", {})
    character = spec.get("character", {})
    reference = spec.get("reference_clip", {})
    output = spec.get("output", {})
    aspect_ratio = spec.get("aspect_ratio", "9:16")

    from workflow.model_profiles import resolve_adapter
    profile = spec.get("profile", "production")
    image_adapter = resolve_adapter(models, "image_gen", "motion_control", profile)
    video_adapter = resolve_adapter(models, "video_gen", "motion_control", profile)
    ffmpeg_adapter = resolve_adapter(models, "ffmpeg", "motion_control", profile)

    nodes: list[dict] = []

    # Step 1: Download the reference clip
    nodes.append({
        "id": "download_clip",
        "adapter": ffmpeg_adapter,
        "config": {
            "operation": "download",
            "url": reference.get("url", ""),
            "start_time": reference.get("start_time", 0),
            "end_time": reference.get("end_time", 10),
            "output_filename": "reference_clip.mp4",
        },
        "depends_on": [],
    })

    # Step 2: Extract a frame from the downloaded clip
    nodes.append({
        "id": "extract_frame",
        "adapter": ffmpeg_adapter,
        "config": {
            "operation": "extract_frame",
            "video_from": "download_clip",
            "timestamp": reference.get("frame_timestamp", 0),
            "output_filename": "reference_frame.png",
        },
        "depends_on": ["download_clip"],
    })

    # Step 3: Generate character replacement frame
    scene_prompt = spec.get("scene_prompt", "")
    if not scene_prompt:
        name = character.get("name", "Person")
        description = character.get("description", "")
        outfit = character.get("outfit", "")
        pose_hint = reference.get("pose_description", "in the same pose as the reference")
        scene_prompt = (
            f"{name}: {description}. {f'Wearing: {outfit}. ' if outfit else ''}"
            f"Pose: {pose_hint}."
        )

    nodes.append({
        "id": "image_gen.character_frame",
        "adapter": image_adapter,
        "config": {
            "prompt": scene_prompt,
            "reference_frame_from": "extract_frame",
            "character": character,
            "aspect_ratio": aspect_ratio,
            "output_filename": "character_frame.png",
        },
        "depends_on": ["extract_frame"],
    })

    # Step 4: Motion-controlled video generation
    nodes.append({
        "id": "video_gen.motion_control",
        "adapter": video_adapter,
        "config": {
            "mode": "motion_control",
            "start_frame_from": "image_gen.character_frame",
            "motion_reference_from": "download_clip",
            "scene_prompt": scene_prompt,
            "camera": spec.get("camera", ""),
            "duration": reference.get("duration", reference.get("end_time", 10) - reference.get("start_time", 0)),
            "aspect_ratio": aspect_ratio,
            "character": character,
            "output_filename": output.get("final_filename", "final.mp4"),
        },
        "depends_on": ["image_gen.character_frame"],
    })

    return {"pipeline_version": 1, "nodes": nodes}
