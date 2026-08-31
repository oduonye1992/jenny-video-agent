"""Registry mapping adapter names to their classes.

Usage:
    from workflow.adapters.registry import get_adapter
    adapter = get_adapter("fal_kling_v3")
    job_id = adapter.submit(config)
"""

from workflow.adapters.base import Adapter

_REGISTRY: dict[str, type[Adapter]] = {}


def register(name: str):
    """Decorator to register an adapter class."""
    def decorator(cls: type[Adapter]):
        _REGISTRY[name] = cls
        return cls
    return decorator


def get_adapter(name: str) -> Adapter:
    """Instantiate and return an adapter by name."""
    if name not in _REGISTRY:
        _try_import(name)
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY.keys()))
        raise ValueError(f"Unknown adapter '{name}'. Available: {available}")
    return _REGISTRY[name]()


def list_adapters() -> list[str]:
    """Return all registered adapter names."""
    return sorted(_REGISTRY.keys())


def _try_import(name: str):
    """Attempt to import the adapter module to trigger registration.

    Tries the exact name first (filenames match adapter names), then falls
    back to scanning all adapter modules in case of any mismatch.
    """
    import importlib
    module_name = f"workflow.adapters.{name}"
    try:
        importlib.import_module(module_name)
        return
    except ImportError:
        pass

    # Fallback: scan all adapter modules to find the right one
    import pathlib
    adapters_dir = pathlib.Path(__file__).parent
    for py_file in adapters_dir.glob("*.py"):
        if py_file.name.startswith("_") or py_file.stem in ("base", "registry"):
            continue
        try:
            importlib.import_module(f"workflow.adapters.{py_file.stem}")
        except ImportError:
            continue
        if name in _REGISTRY:
            return
