"""Compile production specs to pipeline JSON.

This is the entry point for spec → pipeline compilation.
The engine never imports templates directly — it uses this module
or loads a pre-compiled pipeline.json.

Usage (CLI):
    python workflow/compiler.py spec.json                    # compile + save pipeline.json
    python workflow/compiler.py spec.json --graph            # compile + print DAG
    python workflow/compiler.py spec.json --dry-run          # validate only
    python workflow/compiler.py spec.json -o /path/out       # custom output dir

Usage (library):
    from workflow.compiler import compile_spec
    pipeline = compile_spec(spec)
"""

import json
import os
import sys

# Ensure project root is on sys.path when running as script.
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from workflow.dag import DAG
from workflow.templates.registry import get_template, list_templates


def load_spec(spec_path: str) -> dict:
    """Load a production spec from a JSON file."""
    with open(spec_path) as f:
        return json.load(f)


def compile_spec(spec: dict) -> dict:
    """Compile a production spec to pipeline JSON via its registered template.

    Looks up the template by spec["video_type"] and calls its compile function.
    Returns the pipeline dict (with pipeline_version, nodes, etc.).
    """
    video_type = spec.get("video_type", "broll")
    compile_fn = get_template(video_type)
    return compile_fn(spec)


def _topo_order(dag: DAG) -> list[str]:
    """Return step IDs in topological order."""
    visited = set()
    order = []

    def visit(step_id: str):
        if step_id in visited:
            return
        visited.add(step_id)
        step = dag.steps[step_id]
        for dep in step.depends_on:
            visit(dep)
        order.append(step_id)

    for step_id in dag.steps:
        visit(step_id)
    return order


def format_dag_graph(dag: DAG) -> str:
    """Format the DAG as an ASCII visualization."""
    lines = ["DAG Graph:", "=" * 60]
    for step_id in _topo_order(dag):
        step = dag.steps[step_id]
        deps = ", ".join(step.depends_on) if step.depends_on else "(root)"
        lines.append(f"  {step_id}")
        lines.append(f"    adapter: {step.adapter_name}")
        lines.append(f"    depends: {deps}")
    lines.append("=" * 60)
    lines.append(f"Total: {len(dag.steps)} steps")
    return "\n".join(lines)


def format_mermaid(dag: DAG) -> str:
    """Format the DAG as a Mermaid flowchart with cost and category styling."""
    from workflow.cost import COST_PER_STEP

    lines = ["graph TD"]

    # Category → style class mapping
    _CATEGORY_STYLE = {
        "image_gen": "img",
        "image_edit": "img",
        "image_upscale": "img",
        "video_gen": "vid",
        "upscale": "vid",
        "extract_last_frame": "ffm",
        "extract_first_frame": "ffm",
        "tts": "aud",
        "music": "aud",
        "merge_videos": "ffm",
        "mix_audio": "ffm",
        "assemble_slideshow": "ffm",
        "download_clip": "ffm",
        "extract_frame": "ffm",
        "pil_render": "ffm",
    }

    def _node_class(step_id: str, adapter: str) -> str:
        """Determine the style class for a node."""
        for prefix, cls in _CATEGORY_STYLE.items():
            if step_id.startswith(prefix):
                return cls
        # Fallback: infer from adapter name
        if "nano_banana" in adapter or "dreamina" in adapter or "magnific" in adapter:
            return "img"
        if "kling" in adapter or "veo" in adapter or "sora" in adapter or "seedance" in adapter or "hailuo" in adapter or "ltx" in adapter or "topaz" in adapter:
            return "vid"
        if "elevenlabs" in adapter:
            return "aud"
        if "ffmpeg" in adapter or "local_ffmpeg" in adapter or "pil" in adapter:
            return "ffm"
        return ""

    # Nodes
    for step_id in _topo_order(dag):
        step = dag.steps[step_id]
        safe_id = step_id.replace(".", "_").replace("-", "_")
        cost = COST_PER_STEP.get(step.adapter_name, 0.0)
        cost_str = f"${cost:.2f}" if cost > 0 else "free"
        label = f"{step_id}\\n{step.adapter_name} ({cost_str})"
        cls = _node_class(step_id, step.adapter_name)
        lines.append(f"    {safe_id}[\"{label}\"]:::{cls}")

    # Edges
    for step_id in _topo_order(dag):
        step = dag.steps[step_id]
        safe_id = step_id.replace(".", "_").replace("-", "_")
        for dep in step.depends_on:
            safe_dep = dep.replace(".", "_").replace("-", "_")
            lines.append(f"    {safe_dep} --> {safe_id}")

    # Style definitions
    lines.append("")
    lines.append("    classDef img fill:#a78bfa,stroke:#7c3aed,color:#fff")
    lines.append("    classDef vid fill:#60a5fa,stroke:#2563eb,color:#fff")
    lines.append("    classDef aud fill:#f97316,stroke:#ea580c,color:#fff")
    lines.append("    classDef ffm fill:#6b7280,stroke:#4b5563,color:#fff")

    return "\n".join(lines)


def format_mermaid_md(dag: DAG, pipeline: dict | None = None) -> str:
    """Format a full markdown document with Mermaid diagram, cost summary, and legend."""
    from workflow.cost import COST_PER_STEP, estimate_pipeline_cost

    lines = ["# Pipeline DAG", ""]

    # Cost summary
    if pipeline:
        cost = estimate_pipeline_cost(pipeline)
        lines.append(f"**{len(dag.steps)} steps** | **${cost['total']:.2f} estimated**")
        lines.append("")

    # Mermaid block
    lines.append("```mermaid")
    lines.append(format_mermaid(dag))
    lines.append("```")
    lines.append("")

    # Legend
    lines.append("### Legend")
    lines.append("")
    lines.append("| Color | Category |")
    lines.append("|-------|----------|")
    lines.append("| 🟣 Purple | Image gen / edit / upscale |")
    lines.append("| 🔵 Blue | Video gen / upscale |")
    lines.append("| 🟠 Orange | Audio (TTS / music) |")
    lines.append("| ⚫ Grey | FFmpeg / local ops |")
    lines.append("")

    # Cost breakdown table
    if pipeline:
        lines.append("### Cost Breakdown")
        lines.append("")
        lines.append("| Step | Adapter | Cost |")
        lines.append("|------|---------|------|")
        for entry in cost["breakdown"]:
            if entry["cost"] > 0:
                lines.append(f"| {entry['step']} | {entry['adapter']} | ${entry['cost']:.2f} |")
        lines.append(f"| **Total** | | **${cost['total']:.2f}** |")
        lines.append("")

    return "\n".join(lines)


def main():
    import argparse
    from workflow.model_profiles import resolve_all
    from workflow.spec_validator import validate_spec
    from workflow.pipeline_validator import validate_pipeline

    parser = argparse.ArgumentParser(
        description="Compile a production spec to pipeline.json"
    )
    parser.add_argument("spec", nargs="?", help="Path to production spec JSON")
    parser.add_argument("-o", "--output-dir", help="Override output directory")
    parser.add_argument("--graph", action="store_true", help="Print ASCII DAG visualization")
    parser.add_argument("--mermaid", action="store_true", help="Print Mermaid flowchart")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, don't write pipeline.json")
    parser.add_argument("--list-templates", action="store_true", help="List available templates and exit")
    args = parser.parse_args()

    if args.list_templates:
        for name in list_templates():
            print(name)
        return

    if not args.spec:
        parser.error("spec is required (unless using --list-templates)")

    # Load and validate spec
    spec = load_spec(args.spec)
    errors = validate_spec(spec)
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, indent=2), file=sys.stderr)
        sys.exit(1)

    # Resolve model profiles
    spec["models"] = resolve_all(spec)

    # Compile
    pipeline = compile_spec(spec)

    # Validate compiled pipeline
    pipeline_errors = validate_pipeline(pipeline)
    if pipeline_errors:
        print(json.dumps({"valid": False, "errors": pipeline_errors}, indent=2), file=sys.stderr)
        sys.exit(1)

    # Visualization modes
    if args.graph or args.mermaid:
        dag = DAG.from_json(pipeline)
        if args.graph:
            print(format_dag_graph(dag))
        if args.mermaid:
            print(format_mermaid(dag))

    if args.dry_run:
        print(json.dumps({"valid": True, "nodes": len(pipeline.get("nodes", []))}, indent=2))
        return

    # Write pipeline.json + pipeline.mmd
    output_dir = args.output_dir or spec.get("output", {}).get(
        "dir", f"outputs/runs/{spec.get('run_name', 'unnamed')}"
    )
    os.makedirs(output_dir, exist_ok=True)
    pipeline_path = os.path.join(output_dir, "pipeline.json")
    mermaid_path = os.path.join(output_dir, "pipeline.mmd")
    with open(pipeline_path, "w") as f:
        json.dump(pipeline, f, indent=2)

    dag = DAG.from_json(pipeline)
    with open(mermaid_path, "w") as f:
        f.write(format_mermaid(dag))
        f.write("\n")

    print(json.dumps({
        "pipeline_path": pipeline_path,
        "mermaid_path": mermaid_path,
        "nodes": len(pipeline.get("nodes", [])),
        "pipeline_version": pipeline.get("pipeline_version"),
    }, indent=2))


if __name__ == "__main__":
    main()


__all__ = ["compile_spec", "load_spec", "format_dag_graph", "format_mermaid", "format_mermaid_md", "list_templates"]
