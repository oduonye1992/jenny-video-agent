"""Base adapter interface for all generation adapters."""

from abc import ABC, abstractmethod
from enum import Enum


class Status(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Adapter(ABC):
    """Base interface for all generation adapters.

    Async adapters (fal, replicate, elevenlabs) return a job_id from submit()
    and require polling via poll(). Sync adapters (local_ffmpeg, pil_render)
    complete inside submit() and return the output path directly.
    """

    def _preflight(self) -> None:
        """Run health_check() before submit(). Raises RuntimeError on failure."""
        if not self.health_check():
            name = self.__class__.__name__
            raise RuntimeError(f"{name} pre-flight failed. Check API keys and .env file.")

    @abstractmethod
    def submit(self, config: dict) -> str:
        """Submit a job. Returns a job_id (or local file path for sync adapters)."""

    @abstractmethod
    def poll(self, job_id: str) -> tuple[Status, dict]:
        """Check job status. Returns (status, metadata).

        metadata includes:
          - 'progress': float 0-1 (if available)
          - 'elapsed_seconds': float
          - 'error': str (on failure)
          - 'output': str (file path, on completion)
        """

    @abstractmethod
    def get_result(self, job_id: str) -> str:
        """Download/return the output file path. Only valid after COMPLETED status."""

    @property
    @abstractmethod
    def timeout_seconds(self) -> int:
        """Max wait time before treating the job as failed."""

    @property
    def input_types(self) -> dict[str, str]:
        """Expected input types per config key.

        Types: 'image', 'video', 'audio', 'image[]', 'video[]', 'audio[]'.
        Empty dict means no file inputs (e.g. text-to-image generation).
        """
        return {}

    @property
    def output_type(self) -> str:
        """What this adapter produces: 'image', 'video', or 'audio'.

        Empty string means unspecified (backward compat default).
        """
        return ""

    @property
    def is_sync(self) -> bool:
        """True if submit() blocks until done (e.g. local_ffmpeg, pil_render).
        Default False (async)."""
        return False

    def health_check(self) -> bool:
        """Quick check that the adapter's API is reachable and configured.

        Returns True if healthy (default). Adapters can override this to
        verify connectivity or API keys before expensive jobs are submitted.
        """
        return True

    def log_prompt(self, config: dict, payload: dict, model: str = "", notes: str = "") -> str | None:
        """Log the exact API payload for this step to the prompts/ directory.

        Call this in submit() right before sending to the API. The engine
        injects '_prompt_log_dir' and '_step_id' into the config automatically.

        Returns the path to the saved log file, or None if logging is not configured.
        """
        prompt_log_dir = config.get("_prompt_log_dir")
        step_id = config.get("_step_id", "unknown")
        if not prompt_log_dir:
            return None

        from workflow.prompt_log import save
        return save(
            prompt_log_dir=prompt_log_dir,
            step_id=step_id,
            adapter_name=self.__class__.__name__,
            payload=payload,
            model=model,
            notes=notes,
        )
