"""Character sheet generation — builds face prompts, generates images, manages manifests.

A character sheet is a set of 3 face reference images (front, 3/4, speaking)
on plain white backgrounds. Used as identity references for scene placement
via fal_nano_banana_edit.
"""

import json
import os
import shutil
from datetime import datetime, timezone

from workflow.adapters.registry import get_adapter

LIBRARY_ROOT = os.path.join("outputs", "characters")

# The 3 core face shots for a character sheet.
FACE_SHOTS = [
    {
        "face_id": "face_01_front",
        "purpose": "Identity anchor — front face, neutral expression",
        "angle": "straight-on",
        "expression": "neutral",
        "action": "Looking directly at camera, face relaxed, lips closed, eyes open and steady.",
        "camera": "Medium close-up, head and shoulders, straight-on angle.",
    },
    {
        "face_id": "face_02_3q",
        "purpose": "Side profile for angled shots",
        "angle": "3/4 left",
        "expression": "neutral",
        "action": "Head turned slightly to the left, showing three-quarter profile. Expression calm and neutral.",
        "camera": "Medium close-up, head and shoulders, three-quarter left angle.",
    },
    {
        "face_id": "face_03_speaking",
        "purpose": "Dialogue reference — lips parted",
        "angle": "straight-on",
        "expression": "speaking",
        "action": "Lips parted mid-word, eyes engaged, brow slightly lifted as if making a point.",
        "camera": "Medium close-up, head and shoulders, straight-on angle.",
    },
]


def _build_subject(character: dict) -> str:
    """Build the subject description string from a character definition."""
    parts = []
    if character.get("age"):
        parts.append(f"{character['age']}-year-old")
    if character.get("ethnicity"):
        parts.append(character["ethnicity"])
    if character.get("gender"):
        parts.append(character["gender"])
    if character.get("skin_tone"):
        parts.append(f"with {character['skin_tone']} skin")
    if character.get("hair"):
        parts.append(f"and {character['hair']}")
    if character.get("facial_features"):
        parts.append(f"— {character['facial_features']}")
    if character.get("build"):
        parts.append(f"({character['build']} build)")
    return " ".join(parts)


def build_face_prompts(character: dict) -> list[dict]:
    """Build 8 Nano Banana JSON specs for a character sheet.

    Args:
        character: dict with keys: name, age, ethnicity, skin_tone, hair,
                   facial_features, build, vibe.

    Returns:
        List of 8 dicts, each containing face_id, purpose, angle, expression,
        and all Nano Banana spec fields.
    """
    subject = _build_subject(character)
    prompts = []

    for shot in FACE_SHOTS:
        spec = {
            "face_id": shot["face_id"],
            "purpose": shot["purpose"],
            "angle": shot["angle"],
            "expression": shot["expression"],
            "scene_description": (
                "Passport-style headshot against plain white background (#FFFFFF). "
                "Flat, even studio lighting with no shadows. No environment visible."
            ),
            "subject": subject,
            "action": shot["action"],
            "lighting": "Flat, even studio lighting. No directional shadows. No color cast.",
            "camera": shot["camera"],
            "background": "Plain white background (#FFFFFF).",
            "foreground": "Not visible.",
            "mid_ground": "Not visible.",
            "color_palette": "Natural skin tones against pure white.",
            "texture_details": (
                "Visible skin pores, natural skin texture, fine hair strands, "
                "slight oil shine. No smoothing or airbrushing."
            ),
            "mood": "Neutral studio portrait.",
        }
        prompts.append(spec)

    return prompts


def save_manifest(character: dict, faces: list[dict], output_dir: str) -> str:
    """Save a character_sheet.json manifest."""
    manifest = {
        "character_name": character.get("name", "unnamed"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "character_definition": character,
        "schema_version": "1.0",
        "faces": faces,
        "shared_properties": {
            "background": "plain white (#FFFFFF)",
            "lighting": "flat, even studio",
            "crop": "face + shoulders",
            "resolution": "2K",
            "aspect_ratio": "9:16",
        },
    }
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "character_sheet.json")
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
    return path


def load_manifest(path: str) -> dict:
    """Load a character_sheet.json manifest from disk."""
    with open(path) as f:
        return json.load(f)


def generate_character_sheet(
    character: dict,
    output_dir: str,
    adapter_name: str = "fal_nano_banana_v2",
) -> dict:
    """Generate a full character sheet (8 face images + manifest).

    Generates each face individually to allow per-face prompt customization.
    Saves prompt JSON alongside each image.

    Args:
        character: Character definition dict.
        output_dir: Directory to save all outputs.
        adapter_name: Image generation adapter to use.

    Returns:
        dict with keys: manifest_path, face_paths, prompt_paths.
    """
    os.makedirs(output_dir, exist_ok=True)
    adapter = get_adapter(adapter_name)
    prompts = build_face_prompts(character)

    face_paths = []
    prompt_paths = []
    face_records = []

    for spec in prompts:
        face_id = spec["face_id"]
        filename = f"{face_id}.png"

        # Save the prompt spec
        prompt_path = os.path.join(output_dir, f"{face_id}_prompt.json")
        with open(prompt_path, "w") as f:
            json.dump(spec, f, indent=2)
        prompt_paths.append(prompt_path)

        # Build adapter config
        config = {
            "nano_banana_spec": {
                "prompt": {
                    "scene_description": spec["scene_description"],
                    "subject": spec["subject"],
                    "action": spec["action"],
                    "lighting": spec["lighting"],
                    "camera": spec["camera"],
                    "background": spec["background"],
                    "foreground": spec["foreground"],
                    "mid_ground": spec["mid_ground"],
                    "color_palette": spec["color_palette"],
                    "texture_details": spec["texture_details"],
                    "mood": spec["mood"],
                },
            },
            "aspect_ratio": "9:16",
            "resolution": "2K",
            "num_images": 1,
            "output_dir": output_dir,
            "output_filename": filename,
        }

        result_path = adapter.submit(config)
        face_paths.append(result_path)

        face_records.append({
            "face_id": face_id,
            "filename": filename,
            "purpose": spec["purpose"],
            "angle": spec["angle"],
            "expression": spec["expression"],
        })

    manifest_path = save_manifest(
        character=character,
        faces=face_records,
        output_dir=output_dir,
    )

    return {
        "manifest_path": manifest_path,
        "face_paths": face_paths,
        "prompt_paths": prompt_paths,
    }


# --- Reusable Character Library ---

def save_to_library(
    sheet_dir: str,
    character_name: str,
    library_root: str = LIBRARY_ROOT,
) -> str:
    """Copy an approved character sheet to the reusable library."""
    dest = os.path.join(library_root, character_name)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(sheet_dir, dest)
    return dest


def load_from_library(
    character_name: str,
    library_root: str = LIBRARY_ROOT,
) -> dict:
    """Load a character sheet manifest from the library."""
    manifest_path = os.path.join(library_root, character_name, "character_sheet.json")
    return load_manifest(manifest_path)


def list_library(library_root: str = LIBRARY_ROOT) -> list[str]:
    """List all character names in the library."""
    if not os.path.exists(library_root):
        return []
    return [
        d for d in os.listdir(library_root)
        if os.path.isdir(os.path.join(library_root, d))
        and os.path.exists(os.path.join(library_root, d, "character_sheet.json"))
    ]
