"""Shared prompt utilities for video adapters.

Video prompts are written at spec-building time by Claude, following the
model-specific prompting guides. The engine passes them through untouched.
"""


def merge_dialogue(config: dict, **_kwargs) -> str:
    """Return the finished video prompt from the step config.

    The prompt is pre-written at spec time and stored in config["prompt"].
    This function exists as the single entry point that all video adapters call.

    Returns empty string if config uses multi_prompt (Kling 3.0 multi-shot mode),
    since each shot carries its own prompt in the multi_prompt array.
    """
    # Kling v3 multi-shot: prompts are per-shot inside multi_prompt, not top-level
    if config.get("multi_prompt"):
        return ""

    prompt = config.get("prompt", "")
    if not prompt:
        raise ValueError(
            "Step config is missing 'prompt'. Video prompts must be written "
            "at spec-building time following the model-specific guide."
        )
    return prompt
