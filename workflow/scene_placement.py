"""Scene placement — composites a character into different scenes.

Takes a character sheet (directory of face reference images) and places
the character into text-described scenes or reference photo scenes using
fal_nano_banana_edit (text) or fal_nano_banana_scene_transfer (reference).
"""

import json
import os

from workflow.adapters.registry import get_adapter


def _load_ref_paths(character_sheet_dir: str) -> list[str]:
    """Load all face image paths from a character sheet directory."""
    manifest_path = os.path.join(character_sheet_dir, "character_sheet.json")
    with open(manifest_path) as f:
        manifest = json.load(f)

    paths = []
    for face in manifest["faces"]:
        path = os.path.join(character_sheet_dir, face["filename"])
        paths.append(path)
    return paths


def place_in_scene_text(
    character_sheet_dir: str,
    scene_prompt: str,
    output_dir: str,
    output_filename: str,
    adapter_name: str = "fal_nano_banana_edit",
    enable_web_search: bool = True,
) -> str:
    """Place a character into a text-described scene.

    Uses fal_nano_banana_edit with all character sheet refs + scene prompt.

    Args:
        character_sheet_dir: Path to character sheet directory (with manifest).
        scene_prompt: Full scene description (environment + character + wardrobe + pose).
        output_dir: Directory for the output frame.
        output_filename: Filename for the output frame.
        adapter_name: Adapter to use.
        enable_web_search: Enable web search grounding for better realism.

    Returns:
        Path to the generated starting frame.
    """
    ref_paths = _load_ref_paths(character_sheet_dir)
    adapter = get_adapter(adapter_name)
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "reference_images": ref_paths,
        "prompt": scene_prompt,
        "aspect_ratio": "9:16",
        "resolution": "2K",
        "num_images": 1,
        "enable_web_search": enable_web_search,
        "output_dir": output_dir,
        "output_filename": output_filename,
    }

    # Save prompt metadata alongside output
    base_name = os.path.splitext(output_filename)[0]
    prompt_path = os.path.join(output_dir, f"{base_name}_prompt.json")
    with open(prompt_path, "w") as f:
        json.dump({
            "scene_prompt": scene_prompt,
            "reference_images": ref_paths,
            "adapter": adapter_name,
            "enable_web_search": enable_web_search,
        }, f, indent=2)

    return adapter.submit(config)


def place_in_scene_reference(
    reference_image: str,
    character_changes: str,
    output_dir: str,
    output_filename: str,
    adapter_name: str = "fal_nano_banana_scene_transfer",
    enable_web_search: bool = True,
) -> str:
    """Place a character into a scene from a reference photo.

    Uses fal_nano_banana_scene_transfer — Gemini describes the reference,
    then surgical changes swap the character. Does NOT use character sheet
    refs (scene transfer relies on text description only).

    Args:
        reference_image: Path to the reference photo.
        character_changes: RELATIVE changes describing the character swap.
        output_dir: Directory for the output frame.
        output_filename: Filename for the output frame.
        adapter_name: Adapter to use.
        enable_web_search: Enable web search grounding.

    Returns:
        Path to the generated starting frame.
    """
    adapter = get_adapter(adapter_name)
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "reference_image": reference_image,
        "changes": character_changes,
        "aspect_ratio": "9:16",
        "resolution": "2K",
        "num_images": 1,
        "enable_web_search": enable_web_search,
        "output_dir": output_dir,
        "output_filename": output_filename,
    }

    # Save prompt metadata
    base_name = os.path.splitext(output_filename)[0]
    prompt_path = os.path.join(output_dir, f"{base_name}_prompt.json")
    with open(prompt_path, "w") as f:
        json.dump({
            "reference_image": reference_image,
            "character_changes": character_changes,
            "adapter": adapter_name,
            "enable_web_search": enable_web_search,
        }, f, indent=2)

    return adapter.submit(config)
