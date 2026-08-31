"""Registry mapping video type names to template compile functions.

Usage:
    from workflow.templates.registry import get_template, list_templates

    compile_fn = get_template("broll")
    pipeline = compile_fn(spec)

Templates register themselves via the @register decorator, mirroring
the adapter registry pattern.
"""

from typing import Callable

_REGISTRY: dict[str, Callable[[dict], dict]] = {}


def register(name: str):
    """Decorator to register a template compile function."""
    def decorator(fn: Callable[[dict], dict]):
        _REGISTRY[name] = fn
        return fn
    return decorator


def get_template(name: str) -> Callable[[dict], dict]:
    """Look up a template compile function by video type name."""
    if name not in _REGISTRY:
        _try_import(name)
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY.keys()))
        raise ValueError(f"Unknown video type '{name}'. Available: {available}")
    return _REGISTRY[name]


def list_templates() -> list[str]:
    """Return all registered template names."""
    _import_all()
    return sorted(_REGISTRY.keys())


def _try_import(name: str):
    """Attempt to import the template module to trigger registration."""
    import importlib
    try:
        importlib.import_module(f"workflow.templates.{name}")
    except ImportError:
        pass
    if name not in _REGISTRY:
        _import_all()


def _import_all():
    """Import all template modules to populate the registry."""
    import importlib
    import pathlib
    templates_dir = pathlib.Path(__file__).parent
    for py_file in templates_dir.glob("*.py"):
        if py_file.name.startswith("_") or py_file.stem == "registry":
            continue
        try:
            importlib.import_module(f"workflow.templates.{py_file.stem}")
        except ImportError:
            continue
