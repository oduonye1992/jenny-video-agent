"""Tests for OpenAI Sora adapters — health check, cost entries, t2v adapter, and character adapter.

All tests are deterministic — no API calls. The OpenAI client and httpx are mocked.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, ANY

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from workflow.adapters.registry import get_adapter
from workflow.adapters.base import Status
from workflow.cost import COST_PER_STEP


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class TestOpenAIHealthCheck:
    """Tests for check_openai_health()."""

    def test_health_with_key(self):
        from workflow.adapters._health import check_openai_health
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-key"}):
            assert check_openai_health() is True

    def test_health_without_key(self):
        from workflow.adapters._health import check_openai_health
        env = os.environ.copy()
        env.pop("OPENAI_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            assert check_openai_health() is False

    def test_health_empty_key(self):
        from workflow.adapters._health import check_openai_health
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            assert check_openai_health() is False


# ---------------------------------------------------------------------------
# Cost entries
# ---------------------------------------------------------------------------

class TestOpenAISoraCost:
    """Verify all 3 OpenAI Sora cost entries exist with correct values."""

    def test_character_cost(self):
        assert "openai_sora_character" in COST_PER_STEP
        assert COST_PER_STEP["openai_sora_character"] == 0.00

    def test_t2v_cost(self):
        assert "openai_sora_t2v" in COST_PER_STEP
        assert COST_PER_STEP["openai_sora_t2v"] == 0.80

    def test_i2v_cost(self):
        assert "openai_sora_i2v" in COST_PER_STEP
        assert COST_PER_STEP["openai_sora_i2v"] == 0.80


# ---------------------------------------------------------------------------
# OpenAI Sora T2V adapter
# ---------------------------------------------------------------------------

def _mock_openai_client():
    """Create a mock OpenAI client with videos namespace."""
    client = MagicMock()

    # videos.create() returns a Video-like object
    video_obj = MagicMock()
    video_obj.id = "video_test123"
    video_obj.status = "queued"
    client.videos.create.return_value = video_obj

    # videos.retrieve() returns a Video-like object
    client.videos.retrieve.return_value = video_obj

    # videos.download_content() returns bytes
    client.videos.download_content.return_value = b"\x00\x00\x00\x1cftypisom" + b"\x00" * 100

    return client


class TestOpenAISoraT2V:
    """Tests for the openai_sora_t2v adapter."""

    def test_registered(self):
        with patch("workflow.adapters.openai_sora_t2v.OpenAI", return_value=_mock_openai_client()):
            adapter = get_adapter("openai_sora_t2v")
            assert adapter.__class__.__name__ == "OpenAISoraT2VAdapter"

    def test_properties(self):
        with patch("workflow.adapters.openai_sora_t2v.OpenAI", return_value=_mock_openai_client()):
            adapter = get_adapter("openai_sora_t2v")
            assert adapter.input_types == {}
            assert adapter.output_type == "video"
            assert adapter.timeout_seconds == 600
            assert adapter.is_sync is False

    def test_submit_missing_prompt_raises(self, tmp_path):
        mock_client = _mock_openai_client()
        with patch("workflow.adapters.openai_sora_t2v._get_client", return_value=mock_client), \
             patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            adapter = get_adapter("openai_sora_t2v")
            with pytest.raises(ValueError, match="prompt"):
                adapter.submit({
                    "output_dir": str(tmp_path),
                })

    def test_submit_builds_correct_request(self, tmp_path):
        mock_client = _mock_openai_client()
        with patch("workflow.adapters.openai_sora_t2v._get_client", return_value=mock_client), \
             patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            adapter = get_adapter("openai_sora_t2v")
            job_id = adapter.submit({
                "prompt": "A woman walks through a park at sunset.",
                "output_dir": str(tmp_path),
                "duration": 8,
                "resolution": "720p",
                "aspect_ratio": "9:16",
            })

        assert job_id == "video_test123"
        mock_client.videos.create.assert_called_once()
        call_kwargs = mock_client.videos.create.call_args
        # Check positional or keyword args
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        assert kwargs["prompt"] == "A woman walks through a park at sunset."
        assert kwargs["model"] == "sora-2"
        assert kwargs["seconds"] == "8"
        assert kwargs["size"] == "720x1280"
        assert "extra_body" not in kwargs  # no characters

    def test_submit_with_character_ids(self, tmp_path):
        mock_client = _mock_openai_client()
        with patch("workflow.adapters.openai_sora_t2v._get_client", return_value=mock_client), \
             patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            adapter = get_adapter("openai_sora_t2v")
            adapter.submit({
                "prompt": "Nina talks to camera.",
                "output_dir": str(tmp_path),
                "character_ids": ["char_abc123", "char_def456"],
            })

        call_kwargs = mock_client.videos.create.call_args.kwargs
        assert call_kwargs["extra_body"] == {
            "characters": [
                {"id": "char_abc123"},
                {"id": "char_def456"},
            ]
        }

    def test_submit_resolves_character_id_path(self, tmp_path):
        # Write a character.json file
        char_file = tmp_path / "character.json"
        char_file.write_text(json.dumps({"character_id": "char_from_file"}))

        mock_client = _mock_openai_client()
        with patch("workflow.adapters.openai_sora_t2v._get_client", return_value=mock_client), \
             patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            adapter = get_adapter("openai_sora_t2v")
            adapter.submit({
                "prompt": "A character walks.",
                "output_dir": str(tmp_path),
                "character_id_path": str(char_file),
            })

        call_kwargs = mock_client.videos.create.call_args.kwargs
        assert call_kwargs["extra_body"] == {
            "characters": [{"id": "char_from_file"}]
        }

    def test_duration_validation(self, tmp_path):
        """Invalid duration falls back to '8'."""
        mock_client = _mock_openai_client()
        with patch("workflow.adapters.openai_sora_t2v._get_client", return_value=mock_client), \
             patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            adapter = get_adapter("openai_sora_t2v")
            adapter.submit({
                "prompt": "Test prompt for duration validation.",
                "output_dir": str(tmp_path),
                "duration": 20,  # invalid — not 4, 8, or 12
            })

        call_kwargs = mock_client.videos.create.call_args.kwargs
        assert call_kwargs["seconds"] == "8"

    def test_duration_valid_values(self, tmp_path):
        """Valid durations are passed through as strings."""
        mock_client = _mock_openai_client()
        for dur in [4, "4", 8, "8", 12, "12"]:
            mock_client.reset_mock()
            with patch("workflow.adapters.openai_sora_t2v._get_client", return_value=mock_client), \
                 patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
                adapter = get_adapter("openai_sora_t2v")
                adapter.submit({
                    "prompt": "Test prompt.",
                    "output_dir": str(tmp_path),
                    "duration": dur,
                })
            call_kwargs = mock_client.videos.create.call_args.kwargs
            assert call_kwargs["seconds"] == str(dur).rstrip("s")

    def test_size_mapping(self, tmp_path):
        """Verify resolution + aspect_ratio → size mapping."""
        mock_client = _mock_openai_client()
        cases = [
            ("720p", "9:16", "720x1280"),
            ("720p", "16:9", "1280x720"),
            ("1080p", "9:16", "1024x1792"),
            ("1080p", "16:9", "1792x1024"),
        ]
        for resolution, aspect_ratio, expected_size in cases:
            mock_client.reset_mock()
            with patch("workflow.adapters.openai_sora_t2v._get_client", return_value=mock_client), \
                 patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
                adapter = get_adapter("openai_sora_t2v")
                adapter.submit({
                    "prompt": "Test prompt.",
                    "output_dir": str(tmp_path),
                    "resolution": resolution,
                    "aspect_ratio": aspect_ratio,
                })
            call_kwargs = mock_client.videos.create.call_args.kwargs
            assert call_kwargs["size"] == expected_size, \
                f"Expected {expected_size} for {resolution}/{aspect_ratio}, got {call_kwargs['size']}"

    def test_poll_completed_downloads(self, tmp_path):
        """Verify poll() downloads the video on completion."""
        mock_client = _mock_openai_client()

        # Set up retrieve to return completed status
        completed_video = MagicMock()
        completed_video.status = "completed"
        completed_video.progress = 100
        mock_client.videos.retrieve.return_value = completed_video
        mock_download = MagicMock()
        mock_download.iter_bytes.return_value = [b"\x00\x00\x00\x1cftypisom" + b"\x00" * 100]
        mock_client.videos.download_content.return_value = mock_download

        with patch("workflow.adapters.openai_sora_t2v._get_client", return_value=mock_client):
            adapter = get_adapter("openai_sora_t2v")
            adapter._jobs["video_done"] = {
                "output_dir": str(tmp_path),
                "output_filename": "result.mp4",
                "start_time": 1000.0,
            }

            status, meta = adapter.poll("video_done")

        assert status == Status.COMPLETED
        assert meta["progress"] == 1.0
        assert meta["output"] == str(tmp_path / "result.mp4")
        # Verify the file was written
        assert (tmp_path / "result.mp4").exists()
        mock_client.videos.download_content.assert_called_once_with("video_done")

    def test_poll_queued(self):
        """Verify queued status maps to PENDING."""
        mock_client = _mock_openai_client()
        queued_video = MagicMock()
        queued_video.status = "queued"
        queued_video.progress = 0
        mock_client.videos.retrieve.return_value = queued_video

        with patch("workflow.adapters.openai_sora_t2v._get_client", return_value=mock_client):
            adapter = get_adapter("openai_sora_t2v")
            adapter._jobs["video_queued"] = {
                "output_dir": ".",
                "output_filename": "video.mp4",
                "start_time": 1000.0,
            }
            status, meta = adapter.poll("video_queued")

        assert status == Status.PENDING
        assert meta["progress"] == 0.0

    def test_poll_in_progress(self):
        """Verify in_progress status maps to RUNNING."""
        mock_client = _mock_openai_client()
        in_progress_video = MagicMock()
        in_progress_video.status = "in_progress"
        in_progress_video.progress = 50
        mock_client.videos.retrieve.return_value = in_progress_video

        with patch("workflow.adapters.openai_sora_t2v._get_client", return_value=mock_client):
            adapter = get_adapter("openai_sora_t2v")
            adapter._jobs["video_running"] = {
                "output_dir": ".",
                "output_filename": "video.mp4",
                "start_time": 1000.0,
            }
            status, meta = adapter.poll("video_running")

        assert status == Status.RUNNING
        assert meta["progress"] == 0.5

    def test_poll_failed(self):
        """Verify failed status maps to FAILED."""
        mock_client = _mock_openai_client()
        failed_video = MagicMock()
        failed_video.status = "failed"
        failed_video.error = "Content policy violation"
        mock_client.videos.retrieve.return_value = failed_video

        with patch("workflow.adapters.openai_sora_t2v._get_client", return_value=mock_client):
            adapter = get_adapter("openai_sora_t2v")
            adapter._jobs["video_failed"] = {
                "output_dir": ".",
                "output_filename": "video.mp4",
                "start_time": 1000.0,
            }
            status, meta = adapter.poll("video_failed")

        assert status == Status.FAILED
        assert "Content policy violation" in meta["error"]

    def test_get_result_missing_raises(self, tmp_path):
        with patch("workflow.adapters.openai_sora_t2v.OpenAI", return_value=_mock_openai_client()):
            adapter = get_adapter("openai_sora_t2v")
            adapter._jobs["job-missing"] = {
                "output_dir": str(tmp_path),
                "output_filename": "nope.mp4",
            }
            with pytest.raises(FileNotFoundError):
                adapter.get_result("job-missing")

    def test_get_result_found(self, tmp_path):
        output = tmp_path / "found.mp4"
        output.write_bytes(b"\x00\x00\x00\x1cftypisom")

        with patch("workflow.adapters.openai_sora_t2v.OpenAI", return_value=_mock_openai_client()):
            adapter = get_adapter("openai_sora_t2v")
            adapter._jobs["job-found"] = {
                "output_dir": str(tmp_path),
                "output_filename": "found.mp4",
            }
            assert adapter.get_result("job-found") == str(output)


# ---------------------------------------------------------------------------
# OpenAI Sora I2V adapter
# ---------------------------------------------------------------------------

class TestOpenAISoraI2V:
    """Tests for the openai_sora_i2v adapter."""

    def test_registered(self):
        with patch("workflow.adapters.openai_sora_i2v.OpenAI", return_value=_mock_openai_client()):
            adapter = get_adapter("openai_sora_i2v")
            assert adapter.__class__.__name__ == "OpenAISoraI2VAdapter"

    def test_properties(self):
        with patch("workflow.adapters.openai_sora_i2v.OpenAI", return_value=_mock_openai_client()):
            adapter = get_adapter("openai_sora_i2v")
            assert adapter.input_types == {"image_path": "image"}
            assert adapter.output_type == "video"
            assert adapter.timeout_seconds == 600
            assert adapter.is_sync is False

    def test_submit_missing_image_raises(self, tmp_path):
        mock_client = _mock_openai_client()
        with patch("workflow.adapters.openai_sora_i2v._get_client", return_value=mock_client), \
             patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            adapter = get_adapter("openai_sora_i2v")
            with pytest.raises(FileNotFoundError, match="Start frame not found"):
                adapter.submit({
                    "prompt": "A woman walks through a park.",
                    "output_dir": str(tmp_path),
                    "image_path": str(tmp_path / "nonexistent.png"),
                })

    def test_submit_missing_prompt_raises(self, tmp_path):
        # Create a dummy image file
        image_file = tmp_path / "start.png"
        image_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        mock_client = _mock_openai_client()
        with patch("workflow.adapters.openai_sora_i2v._get_client", return_value=mock_client), \
             patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            adapter = get_adapter("openai_sora_i2v")
            with pytest.raises(ValueError, match="prompt"):
                adapter.submit({
                    "output_dir": str(tmp_path),
                    "image_path": str(image_file),
                })

    def test_submit_builds_request_with_image(self, tmp_path):
        # Create a dummy image file
        image_file = tmp_path / "start.png"
        image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        image_file.write_bytes(image_bytes)

        mock_client = _mock_openai_client()
        with patch("workflow.adapters.openai_sora_i2v._get_client", return_value=mock_client), \
             patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            adapter = get_adapter("openai_sora_i2v")
            job_id = adapter.submit({
                "prompt": "A woman walks through a park at sunset.",
                "output_dir": str(tmp_path),
                "image_path": str(image_file),
                "duration": 8,
                "resolution": "720p",
                "aspect_ratio": "9:16",
            })

        assert job_id == "video_test123"
        mock_client.videos.create.assert_called_once()
        call_kwargs = mock_client.videos.create.call_args.kwargs
        assert call_kwargs["prompt"] == "A woman walks through a park at sunset."
        assert call_kwargs["model"] == "sora-2"
        assert call_kwargs["seconds"] == "8"
        assert call_kwargs["size"] == "720x1280"
        assert call_kwargs["input_reference"] == image_bytes
        assert "extra_body" not in call_kwargs  # no characters

    def test_poll_completed_downloads(self, tmp_path):
        """Verify poll() downloads the video on completion."""
        mock_client = _mock_openai_client()

        # Set up retrieve to return completed status
        completed_video = MagicMock()
        completed_video.status = "completed"
        completed_video.progress = 100
        mock_client.videos.retrieve.return_value = completed_video
        mock_download = MagicMock()
        mock_download.iter_bytes.return_value = [b"\x00\x00\x00\x1cftypisom" + b"\x00" * 100]
        mock_client.videos.download_content.return_value = mock_download

        with patch("workflow.adapters.openai_sora_i2v._get_client", return_value=mock_client):
            adapter = get_adapter("openai_sora_i2v")
            adapter._jobs["video_done"] = {
                "output_dir": str(tmp_path),
                "output_filename": "result.mp4",
                "start_time": 1000.0,
            }

            status, meta = adapter.poll("video_done")

        assert status == Status.COMPLETED
        assert meta["progress"] == 1.0
        assert meta["output"] == str(tmp_path / "result.mp4")
        assert (tmp_path / "result.mp4").exists()
        mock_client.videos.download_content.assert_called_once_with("video_done")


# ---------------------------------------------------------------------------
# OpenAI Sora Character adapter
# ---------------------------------------------------------------------------

def _mock_httpx_post_response(character_id="char_abc123", status=None):
    """Create a mock httpx.Response for character creation."""
    resp = MagicMock()
    resp.status_code = 200
    result = {"id": character_id, "name": "Nina"}
    if status:
        result["status"] = status
    resp.json.return_value = result
    resp.raise_for_status.return_value = None
    return resp


class TestOpenAISoraCharacter:
    """Tests for the openai_sora_character adapter."""

    def test_registered(self):
        adapter = get_adapter("openai_sora_character")
        assert adapter.__class__.__name__ == "OpenAISoraCharacterAdapter"

    def test_properties(self):
        adapter = get_adapter("openai_sora_character")
        assert adapter.input_types == {"video_path": "video"}
        assert adapter.output_type == "json"
        assert adapter.timeout_seconds == 300
        assert adapter.is_sync is False

    def test_submit_missing_video_raises(self, tmp_path):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            adapter = get_adapter("openai_sora_character")
            with pytest.raises(FileNotFoundError, match="Video not found"):
                adapter.submit({
                    "video_path": str(tmp_path / "nonexistent.mp4"),
                    "name": "Nina",
                    "output_dir": str(tmp_path),
                })

    def test_submit_missing_name_raises(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00\x00\x00\x1cftypisom" + b"\x00" * 100)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}), \
             patch("workflow.adapters.openai_sora_character.httpx") as mock_httpx:
            adapter = get_adapter("openai_sora_character")
            with pytest.raises(ValueError, match="name"):
                adapter.submit({
                    "video_path": str(video),
                    "output_dir": str(tmp_path),
                })

    def test_submit_builds_correct_request(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00\x00\x00\x1cftypisom" + b"\x00" * 100)

        mock_response = _mock_httpx_post_response("char_test123")

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-key"}), \
             patch("workflow.adapters.openai_sora_character.httpx") as mock_httpx:
            mock_httpx.post.return_value = mock_response
            adapter = get_adapter("openai_sora_character")
            job_id = adapter.submit({
                "video_path": str(video),
                "name": "Nina",
                "output_dir": str(tmp_path),
            })

        assert job_id == "char_test123"
        mock_httpx.post.assert_called_once()
        call_kwargs = mock_httpx.post.call_args
        # Verify URL
        assert call_kwargs.args[0] == "https://api.openai.com/v1/video_characters"
        # Verify auth header
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer sk-test-key"
        # Verify multipart files contains video
        files = call_kwargs.kwargs["files"]
        assert "video" in files
        assert files["video"][0] == "clip.mp4"  # filename
        assert files["video"][2] == "video/mp4"  # content type
        # Verify form data contains name
        assert call_kwargs.kwargs["data"]["name"] == "Nina"

    def test_poll_completed_saves_json(self, tmp_path):
        adapter = get_adapter("openai_sora_character")
        adapter._jobs["char_done123"] = {
            "output_dir": str(tmp_path),
            "output_filename": "character.json",
            "name": "Nina",
            "start_time": 1000.0,
            "completed": True,
            "result": {"id": "char_done123", "name": "Nina"},
        }

        status, meta = adapter.poll("char_done123")

        assert status == Status.COMPLETED
        assert meta["progress"] == 1.0
        assert meta["character_id"] == "char_done123"
        assert meta["output"] == str(tmp_path / "character.json")

        # Verify JSON file contents
        with open(tmp_path / "character.json") as f:
            data = json.load(f)
        assert data["character_id"] == "char_done123"
        assert data["name"] == "Nina"
        assert data["result"]["id"] == "char_done123"

    def test_poll_async_pending(self):
        """Verify async character creation polls correctly."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "char_pending", "status": "queued"}
        mock_response.raise_for_status.return_value = None

        adapter = get_adapter("openai_sora_character")
        adapter._jobs["char_pending"] = {
            "output_dir": ".",
            "output_filename": "character.json",
            "name": "Nina",
            "start_time": 1000.0,
            "completed": False,
            "result": {"id": "char_pending", "status": "in_progress"},
        }

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}), \
             patch("workflow.adapters.openai_sora_character.httpx") as mock_httpx:
            mock_httpx.get.return_value = mock_response
            status, meta = adapter.poll("char_pending")

        assert status == Status.PENDING
        assert meta["progress"] == 0.0

    def test_get_result_missing_raises(self, tmp_path):
        adapter = get_adapter("openai_sora_character")
        adapter._jobs["char-missing"] = {
            "output_dir": str(tmp_path),
            "output_filename": "character.json",
        }
        with pytest.raises(FileNotFoundError):
            adapter.get_result("char-missing")

    def test_get_result_found(self, tmp_path):
        output = tmp_path / "character.json"
        output.write_text('{"character_id": "char_123"}')

        adapter = get_adapter("openai_sora_character")
        adapter._jobs["char-found"] = {
            "output_dir": str(tmp_path),
            "output_filename": "character.json",
        }
        assert adapter.get_result("char-found") == str(output)
