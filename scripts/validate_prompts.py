#!/usr/bin/env python3
"""Prompt format validator.

Recursively scans a directory for prompt files (*_prompt.json, *_prompt.txt)
and checks them for format compliance against the production pipeline rules.

Checks:
  - Image prompts (*_prompt.json): valid JSON, all 11 Nano Banana fields present,
    no empty-string fields.
  - Video prompts (*_prompt.txt): minimum length, no banned vague words,
    model-specific constraints (Sora timestamps, Kling char limits).
  - Voice/music prompts: exist and are non-empty.
  - Dialogue pacing: if creative.json or director.json found, runs dialogue_pacing
    check and reports any OVER/TIGHT shots.

Usage:
    python scripts/validate_prompts.py outputs/concepts/<slug>/
    python scripts/validate_prompts.py outputs/concepts/<slug>/shots/shot_01/
    python scripts/validate_prompts.py outputs/concepts/<slug>/ --pace medium
"""

import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NANO_BANANA_FIELDS = [
    "scene_description",
    "subject_pose_and_expression",
    "clothing_top",
    "clothing_bottom",
    "footwear",
    "background_and_environment",
    "lighting",
    "color_and_grading",
    "camera_and_framing",
    "branding_and_text",
    "overall_style",
]

BANNED_WORDS = ["beautiful", "stunning", "gorgeous", "amazing", "perfect"]
BANNED_PATTERN = re.compile(
    r"\b(" + "|".join(BANNED_WORDS) + r")\b", re.IGNORECASE
)

MIN_VIDEO_PROMPT_CHARS = 100
KLING_SINGLE_LIMIT = 2500
KLING_MULTI_LIMIT = 512

# Folders/filenames that indicate voice or music context
VOICE_MUSIC_INDICATORS = {"voice", "music", "tts", "narration", "audio"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_voice_or_music(filepath: str) -> bool:
    """Heuristic: does this prompt file belong to a voice or music asset?"""
    parts = filepath.lower().replace("\\", "/").split("/")
    basename = os.path.basename(filepath).lower()
    for indicator in VOICE_MUSIC_INDICATORS:
        if indicator in basename:
            return True
        for part in parts:
            if indicator == part:
                return True
    return False


def collect_files(root: str) -> tuple[list[str], list[str], list[str]]:
    """Walk root and return (json_prompts, txt_prompts, pacing_files)."""
    json_prompts = []
    txt_prompts = []
    pacing_files = []

    for dirpath, _dirs, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            if name.endswith("_prompt.json"):
                json_prompts.append(full)
            elif name.endswith("_prompt.txt"):
                txt_prompts.append(full)
            elif name in ("creative.json", "director.json"):
                pacing_files.append(full)

    json_prompts.sort()
    txt_prompts.sort()
    pacing_files.sort()
    return json_prompts, txt_prompts, pacing_files


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def validate_image_prompt(filepath: str) -> list[str]:
    """Validate a Nano Banana image prompt JSON. Returns list of failure messages."""
    failures = []
    rel = os.path.basename(filepath)

    try:
        with open(filepath) as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        failures.append(
            f"{rel}: invalid JSON — {exc}. "
            "Fix the JSON syntax (check for trailing commas, unquoted keys, or missing braces)."
        )
        return failures

    # The 11 fields live inside "prompt" if the full spec structure is used,
    # or at the top level if it's a flat prompt dict.
    prompt_block = data.get("prompt", data)

    for field in NANO_BANANA_FIELDS:
        if field not in prompt_block:
            na_hint = "Not visible." if field in ("clothing_bottom", "footwear", "branding_and_text") else "None."
            failures.append(
                f"{rel}: missing field '{field}'. "
                f"Add {field} field (use '{na_hint}' if not applicable)."
            )
        elif isinstance(prompt_block[field], str) and prompt_block[field].strip() == "":
            na_hint = "Not visible." if field in ("clothing_bottom", "footwear", "branding_and_text") else "None."
            failures.append(
                f"{rel}: field '{field}' is empty string. "
                f"Provide a value or use '{na_hint}' for N/A fields."
            )

    return failures


def validate_video_prompt(filepath: str) -> list[str]:
    """Validate a video prompt text file. Returns list of failure messages."""
    failures = []
    rel = os.path.basename(filepath)

    try:
        with open(filepath) as f:
            content = f.read()
    except OSError as exc:
        failures.append(f"{rel}: cannot read file — {exc}.")
        return failures

    if not content.strip():
        failures.append(
            f"{rel}: file is empty. "
            "Video prompts must describe the scene in detail (minimum 100 chars)."
        )
        return failures

    # Length check
    stripped = content.strip()
    if len(stripped) < MIN_VIDEO_PROMPT_CHARS:
        failures.append(
            f"{rel}: only {len(stripped)} chars (minimum {MIN_VIDEO_PROMPT_CHARS}). "
            "Prompts under 100 chars produce generic AI output. "
            "Add more specific detail about the scene, subject, action, and camera."
        )

    # Banned words
    for match in BANNED_PATTERN.finditer(stripped):
        word = match.group(0)
        pos = match.start()
        failures.append(
            f"{rel}: contains banned word '{word}' at position {pos}. "
            "Replace with a specific visual descriptor "
            "(e.g., 'soft golden light', 'warm amber tone', 'delicate', 'striking')."
        )

    # Model-specific checks based on filename
    name_lower = os.path.basename(filepath).lower()

    # Sora prompts must have timestamp markers (e.g., [0:00], [0:02], 0s-, 2s-)
    if "sora" in name_lower:
        timestamp_pattern = re.compile(r"\[\d+:\d+\]|\d+(\.\d+)?s\s*[-–—]")
        if not timestamp_pattern.search(stripped):
            failures.append(
                f"{rel}: Sora prompt missing timestamp markers. "
                "Sora 2 prompts require timestamps at 0.5-2s intervals "
                "(e.g., '[0:00] Scene opens...' or '0s- Scene opens...')."
            )

    # Kling prompts: char limit
    if "kling" in name_lower:
        # Check for multi-shot (delimited by --- or similar section breaks)
        sections = re.split(r"\n-{3,}\n|\n={3,}\n|\n\[Shot \d+\]", stripped)
        if len(sections) > 1:
            for i, section in enumerate(sections):
                section = section.strip()
                if not section:
                    continue
                if len(section) > KLING_MULTI_LIMIT:
                    failures.append(
                        f"{rel}: Kling multi-shot section {i + 1} is {len(section)} chars "
                        f"(limit {KLING_MULTI_LIMIT}). "
                        "Trim the section — focus on the key action and dialogue, "
                        "cut redundant setting descriptions."
                    )
        else:
            if len(stripped) > KLING_SINGLE_LIMIT:
                failures.append(
                    f"{rel}: Kling prompt is {len(stripped)} chars "
                    f"(limit {KLING_SINGLE_LIMIT}). "
                    "Trim the prompt — focus on scene direction, subject, and action. "
                    "Cut verbose style descriptions."
                )

    return failures


def validate_voice_music_prompt(filepath: str) -> list[str]:
    """Validate a voice/music prompt file. Just check it exists and is non-empty."""
    failures = []
    rel = os.path.basename(filepath)

    try:
        with open(filepath) as f:
            content = f.read()
    except OSError as exc:
        failures.append(f"{rel}: cannot read file — {exc}.")
        return failures

    if not content.strip():
        failures.append(
            f"{rel}: file is empty. "
            "Voice/music prompt files must contain the prompt used for generation."
        )

    return failures


# ---------------------------------------------------------------------------
# Dialogue pacing integration
# ---------------------------------------------------------------------------


def run_dialogue_pacing(pacing_files: list[str], pace: str) -> list[str]:
    """Run dialogue pacing checks on creative.json / director.json files.

    Imports dialogue_pacing.py functions directly rather than shelling out,
    to avoid subprocess overhead and keep everything in one process.
    """
    failures = []

    # Try to import dialogue_pacing from the scripts directory
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    try:
        import dialogue_pacing
    except ImportError:
        # dialogue_pacing.py not available — skip gracefully
        return failures

    wps = dialogue_pacing.PACE_TIERS.get(pace, dialogue_pacing.PACE_TIERS["slow"])

    for filepath in pacing_files:
        rel = os.path.basename(filepath)
        try:
            with open(filepath) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        try:
            fmt = dialogue_pacing.detect_format(data)
        except ValueError:
            continue

        if fmt == "creative":
            title, entries = dialogue_pacing.extract_from_creative(data)
        else:
            title, entries = dialogue_pacing.extract_from_director(data)

        if not entries:
            continue

        results = [
            dialogue_pacing.analyze_shot(e["name"], e["dialogue"], e["duration"], wps)
            for e in entries
        ]

        for r in results:
            if r["status"] == "OVER":
                failures.append(
                    f"{rel}: shot '{r['name']}' has {r['words']} words in {r['duration']}s "
                    f"(max {r['max_words']} at {pace} pace). "
                    f"Cut {r['words_to_cut']} words or extend to ~{r.get('suggested_duration', '?')}s."
                )
            elif r["status"] == "TIGHT":
                failures.append(
                    f"{rel}: shot '{r['name']}' is tight — {r['words']} words in {r['duration']}s "
                    f"(max {r['max_words']} at {pace} pace). "
                    "Fits but leaves little breathing room. Consider trimming a few words."
                )

    return failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = sys.argv[1:]

    if not args:
        print("Usage: python scripts/validate_prompts.py <directory> [--pace slow|medium|fast]")
        print()
        print("Recursively scans for *_prompt.json and *_prompt.txt files")
        print("and checks them for format compliance.")
        sys.exit(1)

    root = args[0]
    if not os.path.isdir(root):
        print(f"Error: '{root}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    # Parse --pace flag
    pace = "slow"
    for i, flag in enumerate(flags):
        if flag == "--pace" and i + 1 < len(flags):
            pace = flags[i + 1]
        elif flag.startswith("--pace="):
            pace = flag.split("=", 1)[1]

    # Collect files
    json_prompts, txt_prompts, pacing_files = collect_files(root)

    if not json_prompts and not txt_prompts and not pacing_files:
        print(f"No prompt files found in {root}")
        sys.exit(0)

    all_failures = []
    pass_count = 0
    fail_count = 0

    # Validate image prompts
    for filepath in json_prompts:
        failures = validate_image_prompt(filepath)
        rel = os.path.relpath(filepath, root)
        if failures:
            fail_count += 1
            for msg in failures:
                print(f"FAIL: {msg}")
        else:
            pass_count += 1
            print(f"PASS: {rel}")
        all_failures.extend(failures)

    # Validate text prompts (video or voice/music)
    for filepath in txt_prompts:
        if is_voice_or_music(filepath):
            failures = validate_voice_music_prompt(filepath)
        else:
            failures = validate_video_prompt(filepath)

        rel = os.path.relpath(filepath, root)
        if failures:
            fail_count += 1
            for msg in failures:
                print(f"FAIL: {msg}")
        else:
            pass_count += 1
            print(f"PASS: {rel}")
        all_failures.extend(failures)

    # Dialogue pacing
    if pacing_files:
        print()
        print("Dialogue Pacing")
        print("=" * 40)
        pacing_failures = run_dialogue_pacing(pacing_files, pace)
        if pacing_failures:
            for msg in pacing_failures:
                print(f"WARN: {msg}")
            all_failures.extend(pacing_failures)
        else:
            for pf in pacing_files:
                print(f"PASS: {os.path.relpath(pf, root)} (dialogue pacing)")

    # Summary
    total = pass_count + fail_count
    print()
    print(f"{'=' * 40}")
    print(f"Results: {pass_count}/{total} files passed")
    if all_failures:
        print(f"         {len(all_failures)} issue(s) found")
        sys.exit(1)
    else:
        print("All checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
