"""Tests for individual adapter registration, config, and argument building.

All tests are deterministic — no API calls. External calls (fal_client, requests,
supabase) are monkeypatched to avoid network I/O.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from workflow.adapters.registry import get_adapter
from workflow.adapters.base import Status
from workflow.cost import COST_PER_STEP


# ---------------------------------------------------------------------------
# fal_topaz_image_upscale
# ---------------------------------------------------------------------------

class TestFalTopazImageUpscale:
    """Tests for the fal_topaz_image_upscale adapter."""

    @pytest.fixture(autouse=True)
    def mock_health_check(self, monkeypatch):
        """Keep payload tests offline; health checks have their own tests."""
        monkeypatch.setattr("workflow.adapters._health.check_fal_health", lambda: True)

    def test_registered(self):
        adapter = get_adapter("fal_topaz_image_upscale")
        assert adapter.__class__.__name__ == "FalTopazImageUpscaleAdapter"

    def test_properties(self):
        adapter = get_adapter("fal_topaz_image_upscale")
        assert adapter.input_types == {"image_path": "image"}
        assert adapter.output_type == "image"
        assert adapter.timeout_seconds == 300
        assert adapter.is_sync is False

    def test_cost_registered(self):
        assert "fal_topaz_image_upscale" in COST_PER_STEP
        assert COST_PER_STEP["fal_topaz_image_upscale"] == 0.04

    def test_submit_builds_correct_arguments(self, tmp_path):
        """Verify submit() builds the right FAL payload from config defaults."""
        # Create a fake input image
        image_path = tmp_path / "input.png"
        image_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        output_dir = tmp_path / "output"

        captured_args = {}
        fake_request = MagicMock()
        fake_request.request_id = "test-request-123"

        def mock_submit(model, arguments):
            captured_args["model"] = model
            captured_args["arguments"] = arguments
            return fake_request

        with patch("workflow.adapters.fal_topaz_image_upscale.upload_to_supabase", return_value="https://example.com/image.png"), \
             patch("workflow.adapters.fal_topaz_image_upscale.fal_client") as mock_fal:
            mock_fal.submit = mock_submit

            adapter = get_adapter("fal_topaz_image_upscale")
            job_id = adapter.submit({
                "image_path": str(image_path),
                "output_dir": str(output_dir),
            })

        assert job_id == "test-request-123"
        assert captured_args["model"] == "fal-ai/topaz/upscale/image"

        args = captured_args["arguments"]
        assert args["image_url"] == "https://example.com/image.png"
        assert args["model"] == "High Fidelity V2"
        assert args["upscale_factor"] == 2
        assert args["crop_to_fill"] is False
        assert args["output_format"] == "jpeg"
        assert args["subject_detection"] == "all"
        assert args["face_enhancement"] is True
        assert args["face_enhancement_creativity"] == 0
        assert args["face_enhancement_strength"] == 0.8

    def test_submit_custom_config(self, tmp_path):
        """Verify submit() respects custom config overrides."""
        image_path = tmp_path / "input.png"
        image_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        output_dir = tmp_path / "output"

        captured_args = {}
        fake_request = MagicMock()
        fake_request.request_id = "test-custom-456"

        def mock_submit(model, arguments):
            captured_args["arguments"] = arguments
            return fake_request

        with patch("workflow.adapters.fal_topaz_image_upscale.upload_to_supabase", return_value="https://example.com/image.png"), \
             patch("workflow.adapters.fal_topaz_image_upscale.fal_client") as mock_fal:
            mock_fal.submit = mock_submit

            adapter = get_adapter("fal_topaz_image_upscale")
            adapter.submit({
                "image_path": str(image_path),
                "output_dir": str(output_dir),
                "model": "standard_v2",
                "upscale_factor": 4,
                "output_format": "png",
                "face_enhancement": False,
                "face_enhancement_creativity": 5,
                "face_enhancement_strength": 0.5,
                "subject_detection": "face",
                "crop_to_fill": True,
                "output_filename": "custom.png",
            })

        args = captured_args["arguments"]
        assert args["model"] == "Standard V2"
        assert args["upscale_factor"] == 4
        assert args["output_format"] == "png"
        assert args["face_enhancement"] is False
        assert args["face_enhancement_creativity"] == 5
        assert args["face_enhancement_strength"] == 0.5
        assert args["subject_detection"] == "face"
        assert args["crop_to_fill"] is True

    def test_upscale_factor_clamped(self, tmp_path):
        """Verify upscale_factor is clamped to 1-4 range."""
        image_path = tmp_path / "input.png"
        image_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        captured_args = {}
        fake_request = MagicMock()
        fake_request.request_id = "test-clamp"

        def mock_submit(model, arguments):
            captured_args["arguments"] = arguments
            return fake_request

        with patch("workflow.adapters.fal_topaz_image_upscale.upload_to_supabase", return_value="https://example.com/image.png"), \
             patch("workflow.adapters.fal_topaz_image_upscale.fal_client") as mock_fal:
            mock_fal.submit = mock_submit

            adapter = get_adapter("fal_topaz_image_upscale")
            adapter.submit({
                "image_path": str(image_path),
                "output_dir": str(tmp_path / "output"),
                "upscale_factor": 10,
            })

        assert captured_args["arguments"]["upscale_factor"] == 4

    def test_invalid_format_defaults_to_jpeg(self, tmp_path):
        """Verify invalid output_format falls back to jpeg."""
        image_path = tmp_path / "input.png"
        image_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        captured_args = {}
        fake_request = MagicMock()
        fake_request.request_id = "test-format"

        def mock_submit(model, arguments):
            captured_args["arguments"] = arguments
            return fake_request

        with patch("workflow.adapters.fal_topaz_image_upscale.upload_to_supabase", return_value="https://example.com/image.png"), \
             patch("workflow.adapters.fal_topaz_image_upscale.fal_client") as mock_fal:
            mock_fal.submit = mock_submit

            adapter = get_adapter("fal_topaz_image_upscale")
            adapter.submit({
                "image_path": str(image_path),
                "output_dir": str(tmp_path / "output"),
                "output_format": "webp",
            })

        assert captured_args["arguments"]["output_format"] == "jpeg"

    def test_missing_image_raises(self, tmp_path):
        adapter = get_adapter("fal_topaz_image_upscale")
        with pytest.raises(FileNotFoundError):
            adapter.submit({
                "image_path": str(tmp_path / "nonexistent.png"),
                "output_dir": str(tmp_path / "output"),
            })

    def test_poll_completed_downloads(self, tmp_path):
        """Verify poll() downloads the result on completion."""
        adapter = get_adapter("fal_topaz_image_upscale")
        adapter._jobs["job-done"] = {
            "output_dir": str(tmp_path),
            "output_filename": "result.jpg",
            "start_time": 1000.0,
        }

        fake_image_data = b"\xff\xd8\xff\xe0" + b"\x00" * 200

        with patch("workflow.adapters.fal_topaz_image_upscale.fal_client") as mock_fal, \
             patch("workflow.adapters.fal_topaz_image_upscale._download") as mock_dl:
            mock_fal.status.return_value = fal_client_completed()
            mock_fal.result.return_value = {"image": {"url": "https://example.com/result.jpg"}}
            mock_fal.Completed = type(fal_client_completed())
            mock_fal.Queued = type("Queued", (), {})
            mock_fal.InProgress = type("InProgress", (), {})

            # Simulate download writing the file
            def write_file(url, dest):
                Path(dest).write_bytes(fake_image_data)
                return dest
            mock_dl.side_effect = write_file

            status, meta = adapter.poll("job-done")

        assert status == Status.COMPLETED
        assert meta["output"] == str(tmp_path / "result.jpg")
        assert meta["progress"] == 1.0

    def test_get_result_missing_raises(self, tmp_path):
        adapter = get_adapter("fal_topaz_image_upscale")
        adapter._jobs["job-missing"] = {
            "output_dir": str(tmp_path),
            "output_filename": "nope.jpg",
        }
        with pytest.raises(FileNotFoundError):
            adapter.get_result("job-missing")

    def test_get_result_found(self, tmp_path):
        output = tmp_path / "found.jpg"
        output.write_bytes(b"\xff\xd8\xff\xe0")

        adapter = get_adapter("fal_topaz_image_upscale")
        adapter._jobs["job-found"] = {
            "output_dir": str(tmp_path),
            "output_filename": "found.jpg",
        }
        assert adapter.get_result("job-found") == str(output)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FalCompleted:
    pass

def fal_client_completed():
    return _FalCompleted()
