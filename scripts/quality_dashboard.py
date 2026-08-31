#!/usr/bin/env python3
"""Quality dashboard — aggregate pipeline-judge scores across all concepts.

Scans outputs/concepts/*/ for completed concepts (those with both creative.json
and director.json), reads any existing judge_report.json files, and produces an
aggregated quality report as markdown.

Usage:
    python scripts/quality_dashboard.py
    python scripts/quality_dashboard.py --output outputs/quality_report.md
    python scripts/quality_dashboard.py --concepts-dir path/to/concepts

Expected judge_report.json schema (produced by pipeline-judge-agent):
{
  "concept": "concept-folder-name",
  "scores": {
    "creative": {
      "hook_strength":        {"score": 1-5, "critique": "..."},
      "angle_specificity":    {"score": 1-5, "critique": "..."},
      "emotional_arc":        {"score": 1-5, "critique": "..."},
      "dialogue_authenticity": {"score": 1-5, "critique": "..."},
      "compliance":           {"score": 1-5, "critique": "..."},
      "scroll_stop_factor":   {"score": 1-5, "critique": "..."},
      "creative_total": 6-30  // sum of all 6 dimensions
    },
    "director": {
      "scroll_stop":               {"score": 1-5, "critique": "..."},
      "phone_reality":             {"score": 1-5, "critique": "..."},
      "emotional_pacing":          {"score": 1-5, "critique": "..."},
      "would_i_actually_do_this":  {"score": 1-5, "critique": "..."},
      "continuity":                {"score": 1-5, "critique": "..."},
      "will_it_render":            {"score": 1-5, "critique": "..."},
      "director_average": 1.0-5.0
    },
    "director_checklist": {
      "<item_name>": {"status": "PASS"|"FAIL", "evidence": "..."},
      // 11 items: phone_test, same_location_consistency, action_overload,
      // avoid_lists, wardrobe_logic, broll_earns_its_place, breathing_room,
      // prop_curation, emotional_progression, self_containment,
      // action_carries_emotion
    }
  },
  "causal_traces": [
    {
      "symptom": "...",
      "stage": "creative|director|creative-reviewer|director-reviewer",
      "root_cause": "rule_violated|rule_missing|upstream_weakness",
      "skill_file": "...",
      "rule_ref": "...",
      "proposed_fix": "..."
    }
  ],
  "pattern_classifications": [
    {
      "pattern": "RULE_VIOLATED|RULE_MISSING|RULE_CONFLICTING|UPSTREAM_CASCADE|REVIEWER_GAP|EXAMPLE_NEEDED",
      "description": "...",
      "affected_files": ["..."],
      "frequency": "systematic|occasional|one-off",
      "severity": "high|medium|low",
      "proposed_update": { ... }
    }
  ],
  "summary": {
    "creative_health": "...",
    "director_health": "...",
    "top_3_systemic_issues": ["...", "...", "..."],
    "rules_to_add": ["..."],
    "rules_to_modify": ["..."],
    "rules_to_remove": ["..."]
  }
}
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

# Scoring dimensions keyed exactly as the judge outputs them
CREATIVE_DIMENSIONS = [
    "hook_strength",
    "angle_specificity",
    "emotional_arc",
    "dialogue_authenticity",
    "compliance",
    "scroll_stop_factor",
]

DIRECTOR_DIMENSIONS = [
    "scroll_stop",
    "phone_reality",
    "emotional_pacing",
    "would_i_actually_do_this",
    "continuity",
    "will_it_render",
]

DIRECTOR_CHECKLIST_ITEMS = [
    "phone_test",
    "same_location_consistency",
    "action_overload",
    "avoid_lists",
    "wardrobe_logic",
    "broll_earns_its_place",
    "breathing_room",
    "prop_curation",
    "emotional_progression",
    "self_containment",
    "action_carries_emotion",
]

LOW_SCORE_THRESHOLD = 3  # scores at or below this are flagged


def discover_concepts(concepts_dir: str) -> list[dict]:
    """Find all concept folders that have both creative.json and director.json.

    Returns a list of dicts with keys: slug, path, has_judge, creative, director, judge.
    """
    concepts = []
    concepts_path = Path(concepts_dir)

    if not concepts_path.is_dir():
        return concepts

    for entry in sorted(concepts_path.iterdir()):
        if not entry.is_dir():
            continue

        creative_path = entry / "creative.json"
        director_path = entry / "director.json"

        if not (creative_path.exists() and director_path.exists()):
            continue

        concept = {
            "slug": entry.name,
            "path": str(entry),
            "has_judge": False,
            "creative": None,
            "director": None,
            "judge": None,
        }

        # Load creative.json for metadata (format, title)
        try:
            with open(creative_path) as f:
                concept["creative"] = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue  # skip corrupt files

        # Load director.json for metadata
        try:
            with open(director_path) as f:
                concept["director"] = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        # Load judge_report.json if present
        judge_path = entry / "judge_report.json"
        if judge_path.exists():
            try:
                with open(judge_path) as f:
                    concept["judge"] = json.load(f)
                    concept["has_judge"] = True
            except (json.JSONDecodeError, OSError):
                pass  # skip corrupt judge files

        concepts.append(concept)

    return concepts


def extract_score(dimension_data) -> float | None:
    """Safely extract a numeric score from a dimension dict or raw value."""
    if isinstance(dimension_data, dict):
        score = dimension_data.get("score")
        if isinstance(score, (int, float)):
            return float(score)
    elif isinstance(dimension_data, (int, float)):
        return float(dimension_data)
    return None


def extract_metadata(concept: dict) -> str:
    """Extract a short metadata string from creative/director data."""
    parts = []
    creative = concept.get("creative") or {}

    fmt = creative.get("format", "")
    if fmt:
        parts.append(fmt)

    # Try to find model info from director shots
    director = concept.get("director") or {}
    shots = director.get("shots", [])
    if shots and isinstance(shots, list):
        for shot in shots:
            model = shot.get("model") or shot.get("adapter") or ""
            if model:
                parts.append(model)
                break

    return ", ".join(parts) if parts else "unknown"


def dim_label(key: str) -> str:
    """Convert snake_case dimension key to readable label."""
    return key.replace("_", " ").title()


def aggregate_scores(concepts: list[dict]) -> dict:
    """Aggregate judge scores across all evaluated concepts.

    Returns a dict with:
      creative_dims: {dim: [scores]}
      director_dims: {dim: [scores]}
      checklist: {item: {"pass": N, "fail": N}}
      causal_traces: [all traces]
      pattern_counts: Counter of pattern types
      per_concept: [{slug, creative_avg, director_avg, metadata}]
      verdicts: Counter of verdicts (APPROVE/REVISE/REJECT)
    """
    result = {
        "creative_dims": defaultdict(list),
        "director_dims": defaultdict(list),
        "checklist": defaultdict(lambda: {"pass": 0, "fail": 0}),
        "causal_traces": [],
        "pattern_counts": Counter(),
        "stage_counts": Counter(),
        "severity_counts": Counter(),
        "per_concept": [],
        "recurring_issues": [],
    }

    for concept in concepts:
        judge = concept.get("judge")
        if not judge:
            continue

        scores = judge.get("scores", {})
        creative_scores = scores.get("creative", {})
        director_scores = scores.get("director", {})
        checklist = scores.get("director_checklist", {})

        # Creative dimensions
        concept_creative_scores = []
        for dim in CREATIVE_DIMENSIONS:
            score = extract_score(creative_scores.get(dim))
            if score is not None:
                result["creative_dims"][dim].append(score)
                concept_creative_scores.append(score)

        # Director dimensions
        concept_director_scores = []
        for dim in DIRECTOR_DIMENSIONS:
            score = extract_score(director_scores.get(dim))
            if score is not None:
                result["director_dims"][dim].append(score)
                concept_director_scores.append(score)

        # Director checklist
        for item in DIRECTOR_CHECKLIST_ITEMS:
            item_data = checklist.get(item, {})
            status = item_data.get("status", "").upper() if isinstance(item_data, dict) else ""
            if status == "PASS":
                result["checklist"][item]["pass"] += 1
            elif status == "FAIL":
                result["checklist"][item]["fail"] += 1

        # Causal traces
        for trace in judge.get("causal_traces", []):
            trace_copy = dict(trace)
            trace_copy["concept"] = concept["slug"]
            result["causal_traces"].append(trace_copy)
            result["stage_counts"][trace.get("stage", "unknown")] += 1

        # Pattern classifications
        for pattern in judge.get("pattern_classifications", []):
            p_type = pattern.get("pattern", "UNKNOWN")
            result["pattern_counts"][p_type] += 1
            severity = pattern.get("severity", "unknown")
            result["severity_counts"][severity] += 1

        # Per-concept summary
        creative_avg = mean(concept_creative_scores) if concept_creative_scores else None
        director_avg = mean(concept_director_scores) if concept_director_scores else None
        overall_avg = None
        if creative_avg is not None and director_avg is not None:
            overall_avg = (creative_avg + director_avg) / 2
        elif creative_avg is not None:
            overall_avg = creative_avg
        elif director_avg is not None:
            overall_avg = director_avg

        result["per_concept"].append({
            "slug": concept["slug"],
            "creative_avg": creative_avg,
            "director_avg": director_avg,
            "overall_avg": overall_avg,
            "metadata": extract_metadata(concept),
        })

    # Identify recurring issues: dimensions below threshold in >20% of concepts
    evaluated = sum(1 for c in concepts if c.get("judge"))
    if evaluated > 0:
        for dim in CREATIVE_DIMENSIONS:
            scores = result["creative_dims"].get(dim, [])
            low_count = sum(1 for s in scores if s <= LOW_SCORE_THRESHOLD)
            if low_count > 0:
                pct = low_count / evaluated * 100
                if pct >= 20:
                    result["recurring_issues"].append(
                        f'"Creative: {dim_label(dim)}" scores {LOW_SCORE_THRESHOLD} or below '
                        f"in {low_count}/{evaluated} concepts ({pct:.0f}%)"
                    )

        for dim in DIRECTOR_DIMENSIONS:
            scores = result["director_dims"].get(dim, [])
            low_count = sum(1 for s in scores if s <= LOW_SCORE_THRESHOLD)
            if low_count > 0:
                pct = low_count / evaluated * 100
                if pct >= 20:
                    result["recurring_issues"].append(
                        f'"Director: {dim_label(dim)}" scores {LOW_SCORE_THRESHOLD} or below '
                        f"in {low_count}/{evaluated} concepts ({pct:.0f}%)"
                    )

        for item in DIRECTOR_CHECKLIST_ITEMS:
            data = result["checklist"].get(item, {"pass": 0, "fail": 0})
            total = data["pass"] + data["fail"]
            if total > 0 and data["fail"] > 0:
                pct = data["fail"] / total * 100
                if pct >= 20:
                    result["recurring_issues"].append(
                        f'Director checklist "{dim_label(item)}" fails '
                        f'in {data["fail"]}/{total} concepts ({pct:.0f}%)'
                    )

    return result


def dim_table_row(dim: str, scores: list[float], total_evaluated: int) -> str:
    """Format a single dimension as a markdown table row."""
    if not scores:
        return f"| {dim_label(dim)} | — | — | — | — |"

    avg = mean(scores)
    lo = min(scores)
    hi = max(scores)
    below = sum(1 for s in scores if s <= LOW_SCORE_THRESHOLD)
    return f"| {dim_label(dim)} | {avg:.1f} | {lo:.0f} | {hi:.0f} | {below} |"


def generate_report(concepts: list[dict], agg: dict) -> str:
    """Generate the full markdown report."""
    total = len(concepts)
    evaluated = sum(1 for c in concepts if c.get("judge"))
    unevaluated = total - evaluated

    # Overall averages
    all_creative = []
    all_director = []
    for dim_scores in agg["creative_dims"].values():
        all_creative.extend(dim_scores)
    for dim_scores in agg["director_dims"].values():
        all_director.extend(dim_scores)

    creative_avg = mean(all_creative) if all_creative else 0
    director_avg = mean(all_director) if all_director else 0

    lines = []
    lines.append("# Quality Dashboard")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # --- Overview ---
    lines.append("## Overview")
    lines.append(f"- Total concepts found: {total}")
    lines.append(f"- Concepts with judge reports: {evaluated}")
    if unevaluated:
        lines.append(f"- Concepts awaiting evaluation: {unevaluated}")
    if evaluated > 0:
        lines.append(f"- Average creative score: {creative_avg:.1f}/5")
        lines.append(f"- Average director score: {director_avg:.1f}/5")
    else:
        lines.append("- No judge reports found — run the pipeline-judge-agent on concepts to populate scores.")
    lines.append("")

    if evaluated == 0:
        # Nothing more to report without scores
        lines.append("## Next Steps")
        lines.append("")
        lines.append("Run the `pipeline-judge-agent` on each concept to generate `judge_report.json` files:")
        lines.append("")
        for c in concepts:
            lines.append(f"- `{c['slug']}/`")
        lines.append("")
        return "\n".join(lines)

    # --- Creative Dimensions ---
    lines.append("## Dimension Breakdown (Creative)")
    lines.append(f"| Dimension | Avg Score | Min | Max | Concepts at/below {LOW_SCORE_THRESHOLD} |")
    lines.append("|-----------|-----------|-----|-----|-------------------|")
    for dim in CREATIVE_DIMENSIONS:
        lines.append(dim_table_row(dim, agg["creative_dims"].get(dim, []), evaluated))
    lines.append("")

    # --- Director Dimensions ---
    lines.append("## Dimension Breakdown (Director)")
    lines.append(f"| Dimension | Avg Score | Min | Max | Concepts at/below {LOW_SCORE_THRESHOLD} |")
    lines.append("|-----------|-----------|-----|-----|-------------------|")
    for dim in DIRECTOR_DIMENSIONS:
        lines.append(dim_table_row(dim, agg["director_dims"].get(dim, []), evaluated))
    lines.append("")

    # --- Director Checklist ---
    has_checklist = any(
        agg["checklist"][item]["pass"] + agg["checklist"][item]["fail"] > 0
        for item in DIRECTOR_CHECKLIST_ITEMS
    )
    if has_checklist:
        lines.append("## Director Checklist Pass Rates")
        lines.append("| Check | Pass | Fail | Pass Rate |")
        lines.append("|-------|------|------|-----------|")
        for item in DIRECTOR_CHECKLIST_ITEMS:
            data = agg["checklist"][item]
            total_checks = data["pass"] + data["fail"]
            if total_checks > 0:
                rate = data["pass"] / total_checks * 100
                lines.append(f"| {dim_label(item)} | {data['pass']} | {data['fail']} | {rate:.0f}% |")
            else:
                lines.append(f"| {dim_label(item)} | — | — | — |")
        lines.append("")

    # --- Recurring Issues ---
    if agg["recurring_issues"]:
        lines.append("## Recurring Issues")
        for issue in agg["recurring_issues"]:
            lines.append(f"- {issue}")
        lines.append("")

    # --- Pattern Classification Summary ---
    if agg["pattern_counts"]:
        lines.append("## Pattern Classifications (across all causal traces)")
        lines.append("| Pattern | Count |")
        lines.append("|---------|-------|")
        for pattern, count in agg["pattern_counts"].most_common():
            lines.append(f"| {pattern} | {count} |")
        lines.append("")

    # --- Stage Attribution ---
    if agg["stage_counts"]:
        lines.append("## Issue Stage Attribution")
        lines.append("| Stage | Issues Traced |")
        lines.append("|-------|--------------|")
        for stage, count in agg["stage_counts"].most_common():
            lines.append(f"| {stage} | {count} |")
        lines.append("")

    # --- Top / Bottom Concepts ---
    ranked = sorted(
        [c for c in agg["per_concept"] if c["overall_avg"] is not None],
        key=lambda c: c["overall_avg"],
        reverse=True,
    )

    if ranked:
        top_n = min(5, len(ranked))
        lines.append("## Top Performing Concepts")
        for i, c in enumerate(ranked[:top_n], 1):
            lines.append(
                f"{i}. **{c['slug']}** ({c['overall_avg']:.1f} avg) — {c['metadata']}"
            )
        lines.append("")

        bottom = list(reversed(ranked))
        bottom_n = min(5, len(bottom))
        # Only show bottom if there are enough concepts and the worst is meaningfully different
        if len(ranked) >= 3:
            lines.append("## Lowest Performing Concepts")
            for i, c in enumerate(bottom[:bottom_n], 1):
                lines.append(
                    f"{i}. **{c['slug']}** ({c['overall_avg']:.1f} avg) — {c['metadata']}"
                )
            lines.append("")

    # --- Unevaluated Concepts ---
    unevaluated_concepts = [c for c in concepts if not c.get("judge")]
    if unevaluated_concepts:
        lines.append("## Awaiting Evaluation")
        for c in unevaluated_concepts:
            lines.append(f"- `{c['slug']}/`")
        lines.append("")

    # --- Frequently Cited Skill Files ---
    skill_file_counts = Counter()
    for trace in agg["causal_traces"]:
        sf = trace.get("skill_file", "")
        if sf:
            skill_file_counts[sf] += 1
    if skill_file_counts:
        lines.append("## Most Cited Skill Files (in causal traces)")
        lines.append("| Skill File | Times Cited |")
        lines.append("|------------|-------------|")
        for sf, count in skill_file_counts.most_common(10):
            lines.append(f"| `{sf}` | {count} |")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Aggregate pipeline-judge scores into a quality dashboard."
    )
    parser.add_argument(
        "--concepts-dir",
        default=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "outputs",
            "concepts",
        ),
        help="Path to the concepts directory (default: outputs/concepts/)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Save report to a file (default: stdout only)",
    )
    args = parser.parse_args()

    concepts = discover_concepts(args.concepts_dir)

    if not concepts:
        print(
            f"No completed concepts found in {args.concepts_dir}\n"
            "A completed concept needs both creative.json and director.json.",
            file=sys.stderr,
        )
        sys.exit(1)

    agg = aggregate_scores(concepts)
    report = generate_report(concepts, agg)

    print(report)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report + "\n")
        print(f"\nReport saved to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
