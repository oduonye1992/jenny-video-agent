"""Tests for _extract_from_spec in the FAL Nano Banana adapter."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workflow.adapters.fal_nano_banana_v2 import _extract_from_spec


class TestExtractFromSpecFullSpec:
    """Full spec -- all fields populated."""

    def test_prompt_is_json_stringified(self):
        spec = {
            "prompt": {
                "scene_description": "A woman meditating",
                "lighting": "Golden hour",
            },
            "negative_prompt": ["watermark", "blurry"],
            "meta": {"aspect_ratio": "9:16"},
        }
        result = _extract_from_spec(spec)
        assert result["prompt"] == json.dumps(spec["prompt"], indent=2)

    def test_negative_prompt_list_joined(self):
        spec = {
            "prompt": {"scene": "test"},
            "negative_prompt": ["watermark", "blurry", "low quality"],
            "meta": {"aspect_ratio": "16:9"},
        }
        result = _extract_from_spec(spec)
        assert result["negative_prompt"] == "watermark, blurry, low quality"

    def test_aspect_ratio_from_meta(self):
        spec = {
            "prompt": {"scene": "test"},
            "negative_prompt": ["watermark"],
            "meta": {"aspect_ratio": "16:9"},
        }
        result = _extract_from_spec(spec)
        assert result["aspect_ratio"] == "16:9"


class TestExtractFromSpecMinimal:
    """Minimal spec -- only prompt object."""

    def test_returns_only_prompt(self):
        spec = {"prompt": {"scene_description": "A calm forest"}}
        result = _extract_from_spec(spec)
        assert "prompt" in result
        assert "negative_prompt" not in result
        assert "aspect_ratio" not in result
        assert "resolution" not in result


class TestExtractFromSpecEmpty:
    """Empty spec -- empty dict returns empty dict."""

    def test_empty_dict(self):
        result = _extract_from_spec({})
        assert result == {}


class TestExtractFromSpecNegativePromptString:
    """Negative prompt as a string passes through unchanged."""

    def test_string_passthrough(self):
        spec = {
            "prompt": {"scene": "test"},
            "negative_prompt": "watermark, distorted hands",
        }
        result = _extract_from_spec(spec)
        assert result["negative_prompt"] == "watermark, distorted hands"


class TestExtractFromSpecAspectRatioFallback:
    """Aspect ratio falls back to generation_settings when meta lacks it."""

    def test_fallback_to_generation_settings(self):
        spec = {
            "prompt": {"scene": "test"},
            "meta": {"intent": "test"},
            "generation_settings": {"aspect_ratio": "4:5"},
        }
        result = _extract_from_spec(spec)
        assert result["aspect_ratio"] == "4:5"

    def test_meta_takes_priority_over_generation_settings(self):
        spec = {
            "prompt": {"scene": "test"},
            "meta": {"aspect_ratio": "1:1"},
            "generation_settings": {"aspect_ratio": "16:9"},
        }
        result = _extract_from_spec(spec)
        assert result["aspect_ratio"] == "1:1"


class TestExtractFromSpecResolution:
    """Resolution extracted from generation_settings."""

    def test_resolution_from_generation_settings(self):
        spec = {
            "prompt": {"scene": "test"},
            "generation_settings": {"resolution": "2K"},
        }
        result = _extract_from_spec(spec)
        assert result["resolution"] == "2K"

    def test_quality_as_resolution_fallback(self):
        spec = {
            "prompt": {"scene": "test"},
            "generation_settings": {"quality": "high"},
        }
        result = _extract_from_spec(spec)
        assert result["resolution"] == "high"


class TestExtractFromSpecPromptStringification:
    """Verify the JSON string contains expected fields with indent=2."""

    def test_json_format(self):
        prompt_obj = {
            "scene_description": "Outdoor cafe",
            "subject_pose_and_expression": "Smiling, seated",
            "lighting": "Afternoon sun",
        }
        spec = {"prompt": prompt_obj}
        result = _extract_from_spec(spec)
        parsed = json.loads(result["prompt"])
        assert parsed == prompt_obj

    def test_indent_two_formatting(self):
        prompt_obj = {"scene_description": "A park", "lighting": "Overcast"}
        spec = {"prompt": prompt_obj}
        result = _extract_from_spec(spec)
        # Verify indent=2 by checking the actual string format
        expected = json.dumps(prompt_obj, indent=2)
        assert result["prompt"] == expected


class TestExtractFromSpecFullNanoBananaSchema:
    """Full Nano Banana JSON schema matching nano-banana-prompt.md."""

    FULL_SPEC = {
        "schema_version": "1.0",
        "meta": {
            "intent": "test",
            "aspect_ratio": "9:16",
            "orientation": "vertical",
        },
        "prompt": {
            "scene_description": "Young woman on couch",
            "subject_pose_and_expression": "Seated, looking at camera",
            "clothing_top": "Sage green linen top",
            "lighting": "Soft window light",
        },
        "negative_prompt": ["watermark", "distorted hands", "AI uncanny valley"],
        "generation_settings": {
            "style": "photorealistic",
            "quality": "high",
            "aspect_ratio": "9:16",
        },
    }

    def test_prompt_extracted_as_json(self):
        result = _extract_from_spec(self.FULL_SPEC)
        parsed = json.loads(result["prompt"])
        assert parsed["scene_description"] == "Young woman on couch"
        assert parsed["subject_pose_and_expression"] == "Seated, looking at camera"
        assert parsed["clothing_top"] == "Sage green linen top"
        assert parsed["lighting"] == "Soft window light"

    def test_negative_prompt_joined(self):
        result = _extract_from_spec(self.FULL_SPEC)
        assert result["negative_prompt"] == "watermark, distorted hands, AI uncanny valley"

    def test_aspect_ratio_from_meta(self):
        result = _extract_from_spec(self.FULL_SPEC)
        assert result["aspect_ratio"] == "9:16"

    def test_resolution_from_quality(self):
        result = _extract_from_spec(self.FULL_SPEC)
        # generation_settings.quality is used as resolution fallback
        assert result["resolution"] == "high"

    def test_all_expected_keys_present(self):
        result = _extract_from_spec(self.FULL_SPEC)
        assert set(result.keys()) == {"prompt", "negative_prompt", "aspect_ratio", "resolution"}
