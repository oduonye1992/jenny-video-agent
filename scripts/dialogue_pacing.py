#!/usr/bin/env python3
"""Dialogue pacing validator.

Checks whether dialogue word count fits within shot duration at a given
speaking pace with ~75% breathing room.

Pace tiers (from scriptwriting.md):
  slow:   ~2.5 words/sec  (confessional, intimate, heavy pauses)
  medium: ~3.0 words/sec  (selfie POV, natural speech)
  fast:   ~3.5 words/sec  (casual, listing, stacking energy)

Usage:
    python scripts/dialogue_pacing.py path/to/creative.json
    python scripts/dialogue_pacing.py path/to/creative.json --pace fast
    python scripts/dialogue_pacing.py path/to/director.json --pace medium
"""

import json
import math
import re
import sys

PACE_TIERS = {
    "slow": 2.5,
    "medium": 3.0,
    "fast": 3.5,
}
DEFAULT_PACE = "slow"
BREATHING_ROOM = 0.75  # 75% of shot duration is available for dialogue


def strip_delivery_notes(text: str) -> str:
    """Remove bracket delivery notes and em-dash pauses from dialogue."""
    # Strip [bracket notes] — delivery directions, not spoken words
    text = re.sub(r"\[.*?\]", "", text)
    # Strip em dashes used as pauses (space-surrounded)
    text = re.sub(r"\s—\s", " ", text)
    return text


def count_words(text: str) -> int:
    """Count spoken words after stripping delivery notes."""
    cleaned = strip_delivery_notes(text)
    words = cleaned.split()
    return len(words)


def analyze_shot(name: str, dialogue: str, duration: float, wps: float) -> dict:
    """Analyze a single shot's dialogue pacing."""
    words = count_words(dialogue)
    available = duration * BREATHING_ROOM
    max_words = int(available * wps)
    hard_max = int(duration * wps)

    if words > hard_max:
        status = "OVER"
    elif words > max_words:
        status = "TIGHT"
    else:
        status = "OK"

    result = {
        "name": name,
        "words": words,
        "duration": duration,
        "available": available,
        "max_words": max_words,
        "status": status,
    }

    if status == "OVER":
        result["suggested_duration"] = math.ceil(words / wps / BREATHING_ROOM)
        result["words_to_cut"] = words - max_words

    return result


def extract_from_creative(data: dict) -> tuple[str, list[dict]]:
    """Extract title and dialogue entries from creative.json."""
    title = data.get("title", "Untitled")
    entries = []
    for beat in data.get("beats", []):
        dialogue = beat.get("dialogue", "")
        if not dialogue or not dialogue.strip():
            continue
        entries.append({
            "name": beat.get("name", "Unnamed"),
            "dialogue": dialogue,
            "duration": beat.get("duration", 8.0),
        })
    return title, entries


def extract_from_director(data: dict) -> tuple[str, list[dict]]:
    """Extract title and dialogue entries from director.json."""
    title = "Director"
    entries = []
    for shot in data.get("shots", []):
        audio = shot.get("audio", {})
        dialogue = audio.get("dialogue", "")
        if not dialogue or not dialogue.strip():
            continue
        entries.append({
            "name": shot.get("beat_name", shot.get("shot_id", "Unnamed")),
            "dialogue": dialogue,
            "duration": shot.get("duration", 8.0),
        })
    return title, entries


def detect_format(data: dict) -> str:
    """Auto-detect whether the JSON is creative or director format."""
    if "beats" in data:
        return "creative"
    if "shots" in data:
        return "director"
    raise ValueError("Unrecognized format — expected 'beats' (creative) or 'shots' (director)")


def format_table(title: str, results: list[dict], pace_name: str, wps: float) -> str:
    """Format the analysis as a readable table."""
    lines = []
    lines.append(f"Dialogue Pacing Analysis: {title}")
    lines.append("=" * len(lines[0]))
    lines.append(f"Pace: {pace_name} ({wps} words/sec)")
    lines.append("")

    # Column widths
    name_w = max(max((len(r["name"]) for r in results), default=4), 4)
    header = f"{'Shot':<{name_w}}  Words  Duration  Avail   Max    Status"
    sep = "\u2500" * len(header)

    lines.append(header)
    lines.append(sep)

    total_words = 0
    total_duration = 0.0
    total_avail = 0.0
    total_max = 0

    for r in results:
        status_icon = {"OK": "\u2713 OK", "TIGHT": "\u26a0 TIGHT", "OVER": "\u2717 OVER"}[r["status"]]
        lines.append(
            f"{r['name']:<{name_w}}  {r['words']:>5}  {r['duration']:>6.1f}s  {r['available']:>4.1f}s  {r['max_words']:>4}    {status_icon}"
        )
        total_words += r["words"]
        total_duration += r["duration"]
        total_avail += r["available"]
        total_max += r["max_words"]

    lines.append(sep)
    lines.append(
        f"{'Total':<{name_w}}  {total_words:>5}  {total_duration:>6.1f}s  {total_avail:>4.1f}s  {total_max:>4}"
    )

    # Summary
    lines.append("")
    over_shots = [r for r in results if r["status"] == "OVER"]
    tight_shots = [r for r in results if r["status"] == "TIGHT"]

    if over_shots:
        lines.append(f"{len(over_shots)} shot(s) over budget. Consider trimming dialogue or extending duration.")
        lines.append("")
        for r in over_shots:
            lines.append(
                f"  {r['name']}: {r['words_to_cut']} words over — "
                f"either cut {r['words_to_cut']} words or extend to ~{r['suggested_duration']}s"
            )

    if tight_shots:
        if over_shots:
            lines.append("")
        lines.append(f"{len(tight_shots)} shot(s) tight — will fit but leaves little breathing room.")

    if not over_shots and not tight_shots:
        lines.append("All shots within budget.")

    return "\n".join(lines)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    if not args:
        print("Usage: python scripts/dialogue_pacing.py <path> [--pace slow|medium|fast]")
        sys.exit(1)

    path = args[0]

    # Parse --pace flag
    pace_name = DEFAULT_PACE
    for i, flag in enumerate(flags):
        if flag == "--pace" and i + 1 < len(flags):
            pace_name = flags[i + 1]
        elif flag.startswith("--pace="):
            pace_name = flag.split("=", 1)[1]

    # Also check raw argv for --pace value that's not a flag
    for i, a in enumerate(sys.argv[1:], 1):
        if a == "--pace" and i + 1 < len(sys.argv):
            pace_name = sys.argv[i + 1]

    if pace_name not in PACE_TIERS:
        print(f"Unknown pace '{pace_name}'. Options: {', '.join(PACE_TIERS.keys())}")
        sys.exit(1)

    wps = PACE_TIERS[pace_name]

    with open(path) as f:
        data = json.load(f)

    fmt = detect_format(data)

    if fmt == "creative":
        title, entries = extract_from_creative(data)
    else:
        title, entries = extract_from_director(data)

    if not entries:
        print("No dialogue found in any shots/beats.")
        sys.exit(0)

    results = [analyze_shot(e["name"], e["dialogue"], e["duration"], wps) for e in entries]
    print(format_table(title, results, pace_name, wps))


if __name__ == "__main__":
    main()
