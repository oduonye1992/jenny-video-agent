"""Shared health check utilities for adapter families."""

import os


def check_fal_health() -> bool:
    """Quick ping to FAL API to verify connectivity.

    Checks that the FAL_KEY environment variable is set and non-empty.
    This avoids submitting expensive jobs that will immediately fail
    due to missing credentials.
    """
    try:
        import fal_client  # noqa: F401 — verify the SDK is installed
        key = os.environ.get("FAL_KEY", "")
        return bool(key)
    except Exception:
        return False


def check_replicate_health() -> bool:
    """Quick check that the Replicate API token is set."""
    try:
        key = os.environ.get("REPLICATE_API_TOKEN", "")
        return bool(key)
    except Exception:
        return False


def check_elevenlabs_health() -> bool:
    """Quick check that the ElevenLabs API key is set."""
    try:
        key = os.environ.get("ELEVENLABS_API_KEY", "")
        return bool(key)
    except Exception:
        return False


def check_freepik_health() -> bool:
    """Quick check that the Freepik API key is set."""
    try:
        key = os.environ.get("FREEPIK_API_KEY", "")
        return bool(key)
    except Exception:
        return False


def check_openai_health() -> bool:
    """Quick check that the OpenAI API key is set."""
    try:
        import openai  # noqa: F401
        key = os.environ.get("OPENAI_API_KEY", "")
        return bool(key)
    except Exception:
        return False
