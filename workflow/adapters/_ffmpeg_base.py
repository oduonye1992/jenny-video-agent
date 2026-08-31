"""Shared utilities for split ffmpeg adapters.

Provides the base class with common ffmpeg subprocess execution,
path validation, and sync adapter behavior.
"""

import os
import subprocess

from workflow.adapters.base import Adapter, Status


class FfmpegBase(Adapter):
    """Base class for individual ffmpeg operation adapters.

    All ffmpeg adapters are sync (blocking) and share the same
    timeout, poll, and get_result behavior.
    """

    @property
    def timeout_seconds(self) -> int:
        return 300

    @property
    def is_sync(self) -> bool:
        return True

    def poll(self, job_id: str) -> tuple[Status, dict]:
        return Status.COMPLETED, {"output": job_id}

    def get_result(self, job_id: str) -> str:
        return job_id

    def _run_ffmpeg(self, cmd: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
        """Run an ffmpeg command and return the result.

        Raises RuntimeError on non-zero exit code.
        """
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout or self.timeout_seconds,
        )
        if result.returncode != 0:
            op_name = self.__class__.__name__
            raise RuntimeError(
                f"{op_name} failed (exit {result.returncode}): "
                f"{result.stderr[-500:]}"
            )
        return result

    @staticmethod
    def _ensure_dir(path: str) -> None:
        """Ensure the parent directory of a file path exists."""
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    @staticmethod
    def _require_file(path: str, label: str = "File") -> None:
        """Raise FileNotFoundError if the path doesn't exist."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"{label} not found: {path}")
