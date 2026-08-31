"""Tests for workflow.compiler and workflow.templates.registry.

All tests are deterministic — no API calls.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from workflow.compiler import compile_spec, format_dag_graph, format_mermaid
from workflow.dag import DAG
from workflow.templates.registry import get_template, list_templates


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def broll_spec():
    return {
        "video_type": "broll",
        "models": {
            "image_gen": {"adapter": "test_img"},
            "video_gen": {"adapter": "test_vid"},
            "upscale": {"adapter": ""},
            "tts": {"adapter": "test_tts"},
            "music": {"adapter": "test_music"},
        },
        "shots": [
            {"scene": "park", "subject": "woman", "action": "walking",
             "lighting": "daylight", "camera": "wide", "color_grade": "warm",
             "style": "UGC", "video_prompt": "SCENE: Woman walking in park."},
        ],
        "narration": {"script": "Test.", "voice_description": "Warm narrator"},
        "music": {"mood": "calm", "prompt": "piano"},
        "output": {"dir": "outputs/runs/test", "final_filename": "final.mp4"},
    }


@pytest.fixture
def talking_head_spec():
    return {
        "video_type": "talking_head",
        "models": {
            "image_gen": {"adapter": "test_img"},
            "video_gen": {"adapter": "test_vid"},
            "upscale": {"adapter": ""},
        },
        "character": {"name": "Nina", "description": "A young woman"},
        "shots": [
            {"scene": "kitchen", "subject": "Nina", "action": "talking",
             "camera": "close-up", "lighting": "warm", "color_grade": "warm",
             "style": "UGC", "dialogue": "[friendly] Hey!", "duration": 5,
             "video_prompt": "SCENE: Nina talks."},
            {"scene": "kitchen", "subject": "Nina", "action": "smiling",
             "camera": "close-up", "lighting": "warm", "color_grade": "warm",
             "style": "UGC", "dialogue": "[warm] Bye!", "duration": 5,
             "video_prompt": "SCENE: Nina smiles."},
        ],
        "output": {"dir": "outputs/runs/test-th", "final_filename": "final.mp4"},
    }


# ── Template Registry ───────────────────────────────────────────────────────


class TestTemplateRegistry:
    def test_list_templates_returns_all_four(self):
        templates = list_templates()
        assert "broll" in templates
        assert "talking_head" in templates
        assert "slideshow" in templates
        assert "motion_control" in templates

    def test_get_template_returns_callable(self):
        fn = get_template("broll")
        assert callable(fn)

    def test_get_template_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown video type"):
            get_template("nonexistent_type")

    def test_registered_templates_are_compile_functions(self):
        """Each registered template should accept a spec dict and return a dict."""
        for name in list_templates():
            fn = get_template(name)
            assert fn.__name__ == "compile"


# ── Compiler ─────────────────────────────────────────────────────────────────


class TestCompileSpec:
    def test_compile_broll(self, broll_spec):
        pipeline = compile_spec(broll_spec)
        assert pipeline["pipeline_version"] == 1
        assert len(pipeline["nodes"]) > 0

    def test_compile_talking_head(self, talking_head_spec):
        pipeline = compile_spec(talking_head_spec)
        assert pipeline["pipeline_version"] == 1
        assert len(pipeline["nodes"]) > 0

    def test_compile_defaults_to_broll(self):
        """If video_type is missing, defaults to broll."""
        spec = {
            "models": {
                "image_gen": {"adapter": "test_img"},
                "video_gen": {"adapter": "test_vid"},
                "upscale": {"adapter": ""},
                "tts": {"adapter": "test_tts"},
                "music": {"adapter": "test_music"},
            },
            "shots": [
                {"scene": "park", "subject": "woman", "action": "walking",
                 "lighting": "daylight", "camera": "wide", "color_grade": "warm",
                 "style": "UGC", "video_prompt": "SCENE: Walking in park."},
            ],
            "narration": {"script": "Test.", "voice_description": "Narrator"},
            "music": {"mood": "calm", "prompt": "piano"},
            "output": {"dir": "outputs/runs/test"},
        }
        pipeline = compile_spec(spec)
        assert pipeline["pipeline_version"] == 1

    def test_compile_unknown_video_type_raises(self):
        with pytest.raises(ValueError, match="Unknown video type"):
            compile_spec({"video_type": "nonexistent"})

    def test_compile_output_is_json_serializable(self, broll_spec):
        import json
        pipeline = compile_spec(broll_spec)
        # Should not raise
        json.dumps(pipeline)

    def test_compile_nodes_have_required_keys(self, broll_spec):
        pipeline = compile_spec(broll_spec)
        for node in pipeline["nodes"]:
            assert "id" in node
            assert "adapter" in node
            assert "config" in node
            assert "depends_on" in node

    def test_compile_round_trip_through_dag(self, talking_head_spec):
        """compile → DAG.from_json → to_json preserves all node IDs."""
        pipeline = compile_spec(talking_head_spec)
        dag = DAG.from_json(pipeline)
        pipeline2 = dag.to_json()
        ids1 = {n["id"] for n in pipeline["nodes"]}
        ids2 = {n["id"] for n in pipeline2["nodes"]}
        assert ids1 == ids2


# ── ASCII Graph ──────────────────────────────────────────────────────────────


class TestFormatDagGraph:
    def test_graph_contains_all_step_ids(self, broll_spec):
        pipeline = compile_spec(broll_spec)
        dag = DAG.from_json(pipeline)
        graph = format_dag_graph(dag)
        for step_id in dag.steps:
            assert step_id in graph

    def test_graph_shows_adapters(self, broll_spec):
        pipeline = compile_spec(broll_spec)
        dag = DAG.from_json(pipeline)
        graph = format_dag_graph(dag)
        for step in dag.steps.values():
            assert step.adapter_name in graph

    def test_graph_shows_root_for_no_deps(self, broll_spec):
        pipeline = compile_spec(broll_spec)
        dag = DAG.from_json(pipeline)
        graph = format_dag_graph(dag)
        assert "(root)" in graph

    def test_graph_shows_total(self, broll_spec):
        pipeline = compile_spec(broll_spec)
        dag = DAG.from_json(pipeline)
        graph = format_dag_graph(dag)
        assert f"Total: {len(dag.steps)} steps" in graph


# ── Mermaid ──────────────────────────────────────────────────────────────────


class TestFormatMermaid:
    def test_mermaid_starts_with_graph_td(self, broll_spec):
        pipeline = compile_spec(broll_spec)
        dag = DAG.from_json(pipeline)
        mermaid = format_mermaid(dag)
        assert mermaid.startswith("graph TD")

    def test_mermaid_contains_all_nodes(self, broll_spec):
        pipeline = compile_spec(broll_spec)
        dag = DAG.from_json(pipeline)
        mermaid = format_mermaid(dag)
        for step_id in dag.steps:
            assert step_id in mermaid

    def test_mermaid_contains_all_adapters(self, broll_spec):
        pipeline = compile_spec(broll_spec)
        dag = DAG.from_json(pipeline)
        mermaid = format_mermaid(dag)
        for step in dag.steps.values():
            assert step.adapter_name in mermaid

    def test_mermaid_edges_present(self, talking_head_spec):
        """Every dependency should appear as an edge (-->)."""
        pipeline = compile_spec(talking_head_spec)
        dag = DAG.from_json(pipeline)
        mermaid = format_mermaid(dag)
        for step in dag.steps.values():
            safe_id = step.step_id.replace(".", "_")
            for dep in step.depends_on:
                safe_dep = dep.replace(".", "_")
                assert f"{safe_dep} --> {safe_id}" in mermaid

    def test_mermaid_no_dot_in_ids(self, talking_head_spec):
        """Mermaid IDs must not contain dots — they're replaced with underscores."""
        pipeline = compile_spec(talking_head_spec)
        dag = DAG.from_json(pipeline)
        mermaid = format_mermaid(dag)
        # Check node definitions (lines with [...]) don't use dots in the ID part
        for line in mermaid.split("\n"):
            line = line.strip()
            if "[" in line:
                node_id = line.split("[")[0].strip()
                assert "." not in node_id, f"Dot in mermaid ID: {node_id}"

    def test_mermaid_valid_syntax_structure(self, broll_spec):
        """Basic structural check: has graph declaration, node defs, and edges."""
        pipeline = compile_spec(broll_spec)
        dag = DAG.from_json(pipeline)
        mermaid = format_mermaid(dag)
        lines = mermaid.strip().split("\n")
        assert lines[0] == "graph TD"
        has_node_def = any("[" in line for line in lines)
        has_edge = any("-->" in line for line in lines)
        assert has_node_def
        assert has_edge

    def test_mermaid_root_nodes_have_no_incoming_edges(self, broll_spec):
        """Root nodes should not appear as targets of edges unless they have deps."""
        pipeline = compile_spec(broll_spec)
        dag = DAG.from_json(pipeline)
        mermaid = format_mermaid(dag)
        for step in dag.steps.values():
            if not step.depends_on:
                safe_id = step.step_id.replace(".", "_")
                # Should not be a target of any edge
                assert f"--> {safe_id}" not in mermaid
