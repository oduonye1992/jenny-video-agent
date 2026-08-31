"""Tests for workflow.pipeline_validator.

All tests are deterministic — no API calls.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from workflow.pipeline_validator import validate_pipeline


def _valid_pipeline():
    """Minimal valid pipeline with known adapters."""
    return {
        "pipeline_version": 1,
        "nodes": [
            {
                "id": "image_gen",
                "adapter": "fal_nano_banana_v2",
                "config": {"prompt": "test", "output_filename": "frame.png"},
                "depends_on": [],
            },
            {
                "id": "video_gen",
                "adapter": "fal_kling_v2",
                "config": {
                    "prompt": "A person walks through a field",
                    "start_frame_from": "image_gen",
                    "duration": 8,
                    "aspect_ratio": "9:16",
                    "output_filename": "clip.mp4",
                },
                "depends_on": ["image_gen"],
            },
        ],
    }


class TestPipelineValidator:
    def test_valid_pipeline_passes(self):
        errors = validate_pipeline(_valid_pipeline())
        assert errors == []

    def test_missing_pipeline_version(self):
        pipeline = _valid_pipeline()
        del pipeline["pipeline_version"]
        errors = validate_pipeline(pipeline)
        assert any("pipeline_version" in e for e in errors)

    def test_unsupported_pipeline_version(self):
        pipeline = _valid_pipeline()
        pipeline["pipeline_version"] = 99
        errors = validate_pipeline(pipeline)
        assert any("Unsupported" in e for e in errors)

    def test_missing_nodes(self):
        pipeline = {"pipeline_version": 1}
        errors = validate_pipeline(pipeline)
        assert any("nodes" in e for e in errors)

    def test_empty_nodes(self):
        pipeline = {"pipeline_version": 1, "nodes": []}
        errors = validate_pipeline(pipeline)
        assert any("empty" in e for e in errors)

    def test_missing_node_id(self):
        pipeline = {
            "pipeline_version": 1,
            "nodes": [{"adapter": "a", "config": {}, "depends_on": []}],
        }
        errors = validate_pipeline(pipeline)
        assert any("'id'" in e for e in errors)

    def test_missing_node_adapter(self):
        pipeline = {
            "pipeline_version": 1,
            "nodes": [{"id": "s1", "config": {}, "depends_on": []}],
        }
        errors = validate_pipeline(pipeline)
        assert any("'adapter'" in e for e in errors)

    def test_duplicate_node_ids(self):
        pipeline = {
            "pipeline_version": 1,
            "nodes": [
                {"id": "s1", "adapter": "fal_nano_banana_v2", "config": {}, "depends_on": []},
                {"id": "s1", "adapter": "fal_kling_v2", "config": {}, "depends_on": []},
            ],
        }
        errors = validate_pipeline(pipeline)
        assert any("Duplicate" in e for e in errors)

    def test_invalid_dependency(self):
        pipeline = {
            "pipeline_version": 1,
            "nodes": [
                {"id": "s1", "adapter": "fal_nano_banana_v2", "config": {}, "depends_on": ["nonexistent"]},
            ],
        }
        errors = validate_pipeline(pipeline)
        assert any("does not exist" in e for e in errors)

    def test_cycle_detection(self):
        pipeline = {
            "pipeline_version": 1,
            "nodes": [
                {"id": "a", "adapter": "fal_nano_banana_v2", "config": {}, "depends_on": ["b"]},
                {"id": "b", "adapter": "fal_nano_banana_v2", "config": {}, "depends_on": ["a"]},
            ],
        }
        errors = validate_pipeline(pipeline)
        assert any("Cycle" in e for e in errors)

    def test_unknown_adapter(self):
        pipeline = {
            "pipeline_version": 1,
            "nodes": [
                {"id": "s1", "adapter": "totally_fake_adapter", "config": {}, "depends_on": []},
            ],
        }
        errors = validate_pipeline(pipeline)
        assert any("unknown adapter" in e for e in errors)

    def test_type_mismatch_video_to_image_input(self):
        """Video output fed to an adapter expecting image input via *_from → type error."""
        pipeline = {
            "pipeline_version": 1,
            "nodes": [
                {
                    "id": "video_step",
                    "adapter": "fal_kling_v2",
                    "config": {},
                    "depends_on": [],
                },
                {
                    "id": "next_video",
                    "adapter": "fal_kling_v2",
                    "config": {"start_frame_from": "video_step"},
                    "depends_on": ["video_step"],
                },
            ],
        }
        errors = validate_pipeline(pipeline)
        # fal_kling_v2 expects start_frame_path to be 'image' type
        # but video_step produces 'video' — this should be a type mismatch
        assert any("Type mismatch" in e for e in errors)

    def test_compatible_types_pass(self):
        """Image output fed to video adapter's start_frame_path — no error."""
        pipeline = _valid_pipeline()
        errors = validate_pipeline(pipeline)
        assert not any("Type mismatch" in e for e in errors)

    def test_split_ffmpeg_adapters_are_known(self):
        """All split ffmpeg adapter names are recognized."""
        for adapter_name in ["ffmpeg_concat", "ffmpeg_mix_audio",
                             "ffmpeg_extract_last_frame", "ffmpeg_extract_first_frame"]:
            pipeline = {
                "pipeline_version": 1,
                "nodes": [
                    {"id": "s1", "adapter": adapter_name, "config": {}, "depends_on": []},
                ],
            }
            errors = validate_pipeline(pipeline)
            assert not any("unknown adapter" in e for e in errors), \
                f"{adapter_name} should be a known adapter"
