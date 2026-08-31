#!/usr/bin/env python3
"""Migrate plan.json → creative.json + director.json

Splits an existing plan.json (which mixes story and production) into the new
two-document model:

  creative.json — WHAT the ad says (story, beats, dialogue, emotion, arc)
  director.json — HOW to shoot it (camera, lighting, color, action, frame source)

Also writes a status.json tracking the concept's current stage.

Usage:
  python scripts/migrate_plan.py outputs/concepts/<slug>
  python scripts/migrate_plan.py --all          # migrates every concept folder
  python scripts/migrate_plan.py --dry-run outputs/concepts/<slug>

The original plan.json is never modified or deleted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from workflow.plan_schema import Plan
from workflow.creative_schema import (
    Creative,
    CreativeCharacter,
    CreativeBeat,
    CreativeAudio,
)
from workflow.director_schema import (
    DirectorPlan,
    DirectorShot,
    DirectorCharacterRef,
    DirectorAudioPlan,
    DirectorFramePlan,
)


def plan_to_creative(plan: Plan) -> Creative:
    """Extract the story layer from a Plan."""
    c = plan.character

    character = CreativeCharacter(
        name=c.name,
        who=c.description,
        age=c.age,
        ethnicity=c.ethnicity,
        hair=c.hair,
        wardrobe=c.wardrobe,
        voice=plan.audio.voice_tone,
    )

    beats: list[CreativeBeat] = []
    for shot in plan.shots:
        # Infer role from position in arc
        role = ""
        if beats:
            idx = len(beats)
            if idx < len(plan.arc):
                role = plan.arc[idx]
        else:
            role = plan.arc[0] if plan.arc else "hook"

        beats.append(CreativeBeat(
            name=shot.name,
            role=role,
            type=shot.type,
            duration=shot.duration,
            emotion="",           # not in old plan — leave blank for director to fill
            action_summary=shot.direction,
            dialogue=shot.dialogue,
            voiceover=shot.voiceover,
            text_overlay=shot.text_overlay,
        ))

    audio = CreativeAudio(
        music_direction=plan.audio.music_mood,
        voice_direction=plan.audio.voice_tone,
        audio_strategy="native",  # default; each beat has its own strategy
    )

    total_duration = sum(s.duration for s in plan.shots)

    return Creative(
        title=plan.title,
        angle=plan.angle,
        arc=plan.arc,
        character=character,
        beats=beats,
        audio=audio,
        hook_variations=plan.hook_variations,
        compliance_notes=plan.compliance_notes,
        target_duration=total_duration,
        target_platform="tiktok",
        version=1,
        status="approved",  # migrated plans are already approved
    )


def plan_to_director(plan: Plan) -> DirectorPlan:
    """Extract the production layer from a Plan."""
    c = plan.character

    # Build a reusable character ref from plan's character block
    char_physical = ". ".join(filter(None, [
        f"Age {c.age}" if c.age else "",
        f"{c.ethnicity}" if c.ethnicity else "",
        f"Hair: {c.hair}" if c.hair else "",
        f"Face: {c.face}" if c.face else "",
        f"Build: {c.build}" if c.build else "",
    ]))

    shots: list[DirectorShot] = []
    for i, s in enumerate(plan.shots):
        shot_id = f"shot_{i + 1:02d}"

        # Map frame_source + frame_source_ref
        frame = DirectorFramePlan(
            strategy=s.frame_source,
            reference_query=s.frame_source_ref if s.frame_source in ("pinterest", "reference_photo") else "",
            edit_from_shot=s.frame_source_ref if s.frame_source == "edit_from" else None,
            chain_from_shot=s.frame_source_ref if s.frame_source == "chain_from" else None,
            image_prompt=s.image_prompt,
            generated_frame=s.start_frame,
        )

        audio = DirectorAudioPlan(
            strategy=s.audio,
            dialogue=s.dialogue,
            dialogue_delivery="",   # not in old plan
            voiceover=s.voiceover,
            voiceover_delivery="",  # not in old plan
            ambient="None.",
        )

        character = DirectorCharacterRef(
            name=c.name,
            physical_description=char_physical,
            wardrobe=c.wardrobe,
            accessories=c.accessories,
            reference_photos=[],
        )

        # Infer role from arc position
        role = plan.arc[i] if i < len(plan.arc) else ""

        shot = DirectorShot(
            shot_id=shot_id,
            beat_name=s.name,
            beat_role=role,
            type=s.type,
            duration=s.duration,
            setting=s.setting,
            camera=s.camera,
            lighting=s.lighting,
            color_grade="",          # not in old plan
            action=s.direction,
            imperfection="",         # not in old plan
            character=character,
            audio=audio,
            frame=frame,
            avoid=[],
            status=s.status,
        )
        shot.update_content_hash()
        shots.append(shot)

    return DirectorPlan(
        version=1,
        creative_version=1,
        aspect_ratio=plan.aspect_ratio,
        profile=plan.profile,
        shots=shots,
        music_prompt=plan.audio.music_prompt,
        voice_design_prompt=plan.audio.voice_prompt,
        voice_id=None,
        status="draft",
    )


def migrate_concept(concept_dir: Path, dry_run: bool = False) -> bool:
    """Migrate a single concept folder. Returns True if migrated."""
    plan_path = concept_dir / "plan.json"
    creative_path = concept_dir / "creative.json"
    director_path = concept_dir / "director.json"
    status_path = concept_dir / "status.json"

    if not plan_path.exists():
        print(f"  SKIP {concept_dir.name} — no plan.json")
        return False

    if creative_path.exists() and director_path.exists():
        print(f"  SKIP {concept_dir.name} — already migrated")
        return False

    # Load
    plan = Plan.load(plan_path)
    creative = plan_to_creative(plan)
    director = plan_to_director(plan)

    if dry_run:
        print(f"  DRY RUN {concept_dir.name}")
        print(f"    creative: {len(creative.beats)} beats, {creative.target_duration}s")
        print(f"    director: {len(director.shots)} shots, {director.aspect_ratio}, {director.profile}")
        return True

    # Write
    creative.save(concept_dir)
    director.save(concept_dir)

    # Write status.json
    status = {
        "stage": "director",  # migrated plans have story done, need director review
        "migrated_from": "plan.json",
    }
    status_path.write_text(json.dumps(status, indent=2))

    # Create per-shot directories
    shots_dir = concept_dir / "shots"
    for shot in director.shots:
        shot_dir = shots_dir / shot.shot_id
        shot_dir.mkdir(parents=True, exist_ok=True)
        (shot_dir / "frame").mkdir(exist_ok=True)
        (shot_dir / "prompts").mkdir(exist_ok=True)
        (shot_dir / "versions").mkdir(exist_ok=True)

        # If there's an existing start_frame, copy reference into shot dir
        if shot.frame.generated_frame:
            src = Path(shot.frame.generated_frame)
            if src.exists():
                import shutil
                dest = shot_dir / "frame" / "anchor.png"
                shutil.copy2(src, dest)

    print(f"  OK {concept_dir.name}")
    print(f"    creative.json — {len(creative.beats)} beats")
    print(f"    director.json — {len(director.shots)} shots")
    print(f"    status.json   — stage: director")
    print(f"    shots/        — {len(director.shots)} shot directories")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Migrate plan.json → creative.json + director.json"
    )
    parser.add_argument(
        "concept_dir",
        nargs="?",
        help="Path to a specific concept directory",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Migrate all concept folders in outputs/concepts/",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without writing files",
    )
    args = parser.parse_args()

    if not args.concept_dir and not args.all:
        parser.error("Provide a concept directory or use --all")

    if args.all:
        concepts_root = PROJECT_ROOT / "outputs" / "concepts"
        if not concepts_root.exists():
            print(f"No concepts directory at {concepts_root}")
            sys.exit(1)
        dirs = sorted(d for d in concepts_root.iterdir() if d.is_dir())
    else:
        dirs = [Path(args.concept_dir)]

    migrated = 0
    for d in dirs:
        if not d.exists():
            print(f"  SKIP {d} — does not exist")
            continue
        if migrate_concept(d, dry_run=args.dry_run):
            migrated += 1

    print(f"\n{'Would migrate' if args.dry_run else 'Migrated'} {migrated} concept(s)")


if __name__ == "__main__":
    main()
