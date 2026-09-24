"""Neutral interface to the native task runtime this pipeline compiles against.

The pipeline is a compiler and gate-keeper: it decides what a task must contain and
what counts as admissible, but it deliberately does **not** implement the simulated
world, the native API surface or the scorer.  Those live in a separate *native runtime*
that the operator supplies.

This module is the single place where the pipeline reaches the runtime, so the
coupling is explicit and replaceable:

* ``runtime_pin()`` returns the identifier the pipeline binds its artifacts to.  It is
  read from the environment (``ASSETFORGE_RUNTIME_PIN``) and defaults to the value the
  artifacts in this repository were frozen against.  Every catalog and asset carries
  this identifier, and consumers verify it, so an operator who runs a different runtime
  build re-pins once here.
* ``world_state_type()`` / ``assertion_handlers()`` / ``domain_dataset()`` load the
  runtime lazily and raise a single, explanatory error when it is absent, instead of
  surfacing an import error from deep inside a caller.

Supplying the runtime is the operator's job, exactly like supplying provider
credentials: install it, then point ``ASSETFORGE_RUNTIME_ROOT`` at it if it is not
already importable.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# The identifier the artifacts here were frozen against.  Override with
# ASSETFORGE_RUNTIME_PIN when running against another runtime build.
DEFAULT_RUNTIME_PIN = "assetforge-runtime-1"
# Candidate module names for the native runtime.  The first one that is importable wins, so an
# operator who installs the runtime under any of these names needs no configuration; setting
# ASSETFORGE_RUNTIME_PACKAGE overrides the search.
RUNTIME_PACKAGE_CANDIDATES = (
    os.environ.get("ASSETFORGE_RUNTIME_PACKAGE"),
    "native_runtime",
)
_RESOLVED = {"name": None}


def runtime_package() -> str:
    """Importable name of the native runtime package, resolved once."""
    if _RESOLVED["name"]:
        return _RESOLVED["name"]
    _ensure_importable()
    import importlib.util
    for name in RUNTIME_PACKAGE_CANDIDATES:
        if not name:
            continue
        try:
            if importlib.util.find_spec(name) is not None:
                _RESOLVED["name"] = name
                return name
        except (ImportError, ValueError):
            continue
    return "native_runtime"

_MISSING = (
    "The native runtime is not available in this environment. This pipeline compiles and "
    "validates tasks against a separate native runtime, which the operator supplies (the same "
    "way provider credentials are supplied). Install the runtime, or set ASSETFORGE_RUNTIME_ROOT "
    "to the directory that contains the '{pkg}' package, then retry."
).format(pkg=", ".join(c for c in RUNTIME_PACKAGE_CANDIDATES if c))


def runtime_pin() -> str:
    """The runtime identifier that artifacts in this repository are bound to."""
    return os.environ.get("ASSETFORGE_RUNTIME_PIN") or DEFAULT_RUNTIME_PIN


def _ensure_importable() -> None:
    root = os.environ.get("ASSETFORGE_RUNTIME_ROOT")
    if root:
        p = str(Path(root).resolve())
        if p not in sys.path:
            sys.path.insert(0, p)


def _import(module: str):
    _ensure_importable()
    try:
        return __import__(module, fromlist=["_"])
    except ImportError as exc:
        raise RuntimeError(_MISSING + f"  (tried to import {module!r})") from exc


def world_state_type():
    """The runtime's world-state model class (its fields describe the legal world shape)."""
    return _import("schema").WorldState


def assertion_handlers() -> set[str]:
    """Names of the assertions the runtime registers as available."""
    registry = _import("rubric.registry").AssertionRegistry
    return set(registry._handlers)


def rubric_module():
    """The runtime's rubric module (assertions, scoring helpers, registry)."""
    return _import("rubric")


def api_module():
    """The runtime's native API module (fetch, search, tool catalogue)."""
    return _import("tools.api")


def domain_dataset(domain: str):
    """Iterable of released tasks for one business domain, used for structural analysis."""
    return _import("domains").get_domain_dataset(domain)


def is_available() -> bool:
    try:
        _ensure_importable()
        import importlib.util
        return runtime_package() and importlib.util.find_spec(runtime_package()) is not None
    except Exception:
        return False
