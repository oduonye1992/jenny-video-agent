"""Compile-time validation for pipeline JSON.

Validates structure, dependencies, cycles, adapter names, and type compatibility
before execution. Called from --compile, --pipeline, and --dry-run modes.
"""

from workflow.adapters.registry import get_adapter
from workflow.spec_validator import KNOWN_ADAPTERS, PROMPT_CHAR_LIMITS


# --- Check 9: Required config keys per adapter ---
VIDEO_GEN_ADAPTERS = {
    "fal_veo_v3_flf",
    "fal_kling_v2",
    "fal_kling_v3",
    "fal_sora_v2",
    "fal_seedance_v1_5",
    "fal_hailuo_02",
    "fal_ltx_v2",
}

REQUIRED_CONFIG: dict[str, set[str]] = {
    # Video gen: need a prompt and either start_frame_path or start_frame_from
    "fal_veo_v3_flf": {"prompt", "duration", "aspect_ratio"},
    "fal_kling_v2": {"prompt", "duration", "aspect_ratio"},
    "fal_kling_v3": {"prompt", "duration", "aspect_ratio"},
    "fal_sora_v2": {"prompt", "duration", "aspect_ratio"},
    "fal_sora_v2_t2v": {"prompt", "duration", "aspect_ratio"},
    "fal_veo_v3_t2v": {"prompt", "duration", "aspect_ratio"},
    "fal_kling_v3_t2v": {"prompt", "duration", "aspect_ratio"},
    "fal_seedance_v1_5": {"prompt", "duration", "aspect_ratio"},
    "fal_hailuo_02": {"prompt", "duration", "aspect_ratio"},
    "fal_ltx_v2": {"prompt", "duration", "aspect_ratio"},

    # Video upscale
    "fal_topaz_upscale": {"video_from", "aspect_ratio"},

    # Image upscale
    "freepik_magnific_upscale": {"image_from"},

    # TTS
    "elevenlabs_tts": {"script"},

    # FFmpeg concat
    "ffmpeg_concat": {"clips_from"},

    # FFmpeg mix audio - at minimum needs video
    "ffmpeg_mix_audio": {"video_from"},

    # FFmpeg frame extraction
    "ffmpeg_extract_last_frame": {"video_from"},
    "ffmpeg_extract_first_frame": {"video_from"},
}


def validate_pipeline(pipeline: dict) -> list[str]:
    """Validate a pipeline JSON dict. Returns list of error strings (empty = valid)."""
    errors: list[str] = []

    # 1. pipeline_version exists and is supported
    version = pipeline.get("pipeline_version")
    if version is None:
        errors.append("Missing 'pipeline_version' field")
    elif version not in (1,):
        errors.append(f"Unsupported pipeline_version '{version}'. Supported: 1")

    # 2. nodes is a non-empty list
    nodes = pipeline.get("nodes")
    if nodes is None:
        errors.append("Missing 'nodes' field")
        return errors
    if not isinstance(nodes, list):
        errors.append("'nodes' must be a list")
        return errors
    if len(nodes) == 0:
        errors.append("'nodes' must not be empty")
        return errors

    # 3. Each node has required fields
    node_ids: set[str] = set()
    node_map: dict[str, dict] = {}
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"Node at index {i} must be a dict")
            continue

        node_id = node.get("id")
        if not node_id:
            errors.append(f"Node at index {i} missing 'id' field")
            continue

        if not node.get("adapter"):
            errors.append(f"Node '{node_id}' missing 'adapter' field")
        if "config" not in node:
            errors.append(f"Node '{node_id}' missing 'config' field")
        if "depends_on" not in node:
            errors.append(f"Node '{node_id}' missing 'depends_on' field")

        # 4. No duplicate node IDs
        if node_id in node_ids:
            errors.append(f"Duplicate node ID '{node_id}'")
        node_ids.add(node_id)
        node_map[node_id] = node

    if errors:
        return errors

    # 5. All depends_on refs point to existing node IDs
    for node in nodes:
        node_id = node["id"]
        for dep in node.get("depends_on", []):
            if dep not in node_ids:
                errors.append(
                    f"Node '{node_id}' depends on '{dep}' which does not exist"
                )

    # 6. No cycles (topological sort)
    cycle_errors = _detect_cycles(node_map)
    errors.extend(cycle_errors)

    if errors:
        return errors

    # 7. Adapter names exist in the known set
    for node in nodes:
        adapter_name = node["adapter"]
        if adapter_name not in KNOWN_ADAPTERS:
            errors.append(
                f"Node '{node['id']}' uses unknown adapter '{adapter_name}'"
            )

    # 8. Type checking: verify *_from refs have compatible types
    type_errors = _check_type_compatibility(node_map)
    errors.extend(type_errors)

    # 9. Required config keys per adapter
    for node in nodes:
        node_id = node["id"]
        adapter_name = node["adapter"]
        config = node.get("config", {})

        required_keys = REQUIRED_CONFIG.get(adapter_name)
        if required_keys:
            missing = required_keys - set(config.keys())
            if missing:
                errors.append(
                    f"Node '{node_id}' (adapter '{adapter_name}') missing required "
                    f"config keys: {', '.join(sorted(missing))}"
                )

        # Video gen adapters must have either start_frame_path or start_frame_from
        if adapter_name in VIDEO_GEN_ADAPTERS:
            has_start_frame_path = "start_frame_path" in config
            has_start_frame_from = "start_frame_from" in config
            if not has_start_frame_path and not has_start_frame_from:
                errors.append(
                    f"Node '{node_id}' (adapter '{adapter_name}') must have either "
                    "'start_frame_path' or 'start_frame_from' in config"
                )

        # Music adapter: must have either prompt or sections, not both
        if adapter_name == "elevenlabs_music":
            has_prompt = "prompt" in config
            has_sections = "sections" in config
            if not has_prompt and not has_sections:
                errors.append(
                    f"Node '{node_id}' (adapter 'elevenlabs_music') must have either "
                    "'prompt' or 'sections' in config"
                )
            elif has_prompt and has_sections:
                errors.append(
                    f"Node '{node_id}' (adapter 'elevenlabs_music') has both 'prompt' "
                    "and 'sections' — use one or the other, not both"
                )

    # 10. output_filename check (warning, not error — prefixed with "Warning:")
    for node in nodes:
        config = node.get("config", {})
        if "output_filename" not in config:
            errors.append(
                f"Warning: Node '{node['id']}' has no 'output_filename' in config"
            )

    # 11. Prompt length limits for video gen nodes
    for node in nodes:
        adapter_name = node["adapter"]
        config = node.get("config", {})
        prompt = config.get("prompt", "")
        if prompt and adapter_name in PROMPT_CHAR_LIMITS:
            char_limit = PROMPT_CHAR_LIMITS[adapter_name]
            prompt_len = len(prompt.strip())
            if prompt_len > char_limit:
                errors.append(
                    f"Node '{node['id']}' prompt is {prompt_len} chars but adapter "
                    f"'{adapter_name}' has a {char_limit}-char limit. "
                    f"Condense by ~{prompt_len - char_limit} chars."
                )

    # 12. Validate depends_on matches *_from references
    for node in nodes:
        node_id = node["id"]
        config = node.get("config", {})
        deps = set(node.get("depends_on", []))

        for key, value in config.items():
            if not key.endswith("_from"):
                continue
            # _from values can be a single ref string or a list of refs
            refs = value if isinstance(value, list) else [value]
            for ref in refs:
                if not isinstance(ref, str):
                    continue
                # Only check refs that point to other node IDs
                if ref in node_ids and ref not in deps:
                    errors.append(
                        f"Node '{node_id}' references '{ref}' via '{key}' but "
                        f"'{ref}' is not in its depends_on list"
                    )

    return errors


def _detect_cycles(node_map: dict[str, dict]) -> list[str]:
    """Detect cycles in the DAG via DFS. Returns error strings for any cycles found."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {nid: WHITE for nid in node_map}
    errors = []

    def dfs(nid: str, path: list[str]):
        color[nid] = GRAY
        path.append(nid)
        for dep in node_map[nid].get("depends_on", []):
            if dep not in color:
                continue
            if color[dep] == GRAY:
                cycle_start = path.index(dep)
                cycle = path[cycle_start:] + [dep]
                errors.append(
                    f"Cycle detected: {' → '.join(cycle)}"
                )
            elif color[dep] == WHITE:
                dfs(dep, path)
        path.pop()
        color[nid] = BLACK

    for nid in node_map:
        if color[nid] == WHITE:
            dfs(nid, [])

    return errors


def _get_adapter_output_type(adapter_name: str) -> str:
    """Get the output_type of an adapter by name. Returns '' if unknown."""
    try:
        adapter = get_adapter(adapter_name)
        return adapter.output_type
    except (ValueError, Exception):
        return ""


def _get_adapter_input_types(adapter_name: str) -> dict[str, str]:
    """Get the input_types of an adapter by name. Returns {} if unknown."""
    try:
        adapter = get_adapter(adapter_name)
        return adapter.input_types
    except (ValueError, Exception):
        return {}


def _check_type_compatibility(node_map: dict[str, dict]) -> list[str]:
    """Check that *_from references have compatible types between producer and consumer."""
    errors = []

    for node_id, node in node_map.items():
        config = node.get("config", {})
        consumer_adapter = node["adapter"]
        consumer_inputs = _get_adapter_input_types(consumer_adapter)

        if not consumer_inputs:
            continue

        for key, value in config.items():
            if not key.endswith("_from"):
                continue

            # Determine the target config key that the consumer expects
            target_key = key.replace("_from", "_path")

            # Array refs
            if isinstance(value, list):
                # e.g., clips_from → clip_paths
                base = key.replace("_from", "")
                if base.endswith("s"):
                    target_key = f"{base[:-1]}_paths"
                else:
                    target_key = f"{base}_paths"

                expected_type = consumer_inputs.get(target_key, "")
                if not expected_type:
                    continue

                # Strip array suffix for element comparison
                base_type = expected_type.rstrip("[]")
                for ref_id in value:
                    if ref_id not in node_map:
                        continue
                    producer_adapter = node_map[ref_id]["adapter"]
                    producer_type = _get_adapter_output_type(producer_adapter)
                    if producer_type and producer_type != base_type:
                        errors.append(
                            f"Type mismatch: node '{node_id}' expects {target_key} "
                            f"of type '{expected_type}' but '{ref_id}' produces "
                            f"'{producer_type}' (adapter '{producer_adapter}')"
                        )
            else:
                # Single ref
                expected_type = consumer_inputs.get(target_key, "")
                if not expected_type:
                    continue

                ref_id = value
                if ref_id not in node_map:
                    continue
                producer_adapter = node_map[ref_id]["adapter"]
                producer_type = _get_adapter_output_type(producer_adapter)
                if producer_type and producer_type != expected_type:
                    errors.append(
                        f"Type mismatch: node '{node_id}' expects {target_key} "
                        f"of type '{expected_type}' but '{ref_id}' produces "
                        f"'{producer_type}' (adapter '{producer_adapter}')"
                    )

    return errors
