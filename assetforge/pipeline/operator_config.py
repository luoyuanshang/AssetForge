"""Operator-facing configuration, resolved from the environment.

AssetForge reads its settings through this module so that the operator-facing names are
stable and documented, and the internal variable names used by individual stage modules stay
an implementation detail.

Recognised variables
--------------------
``ASSETFORGE_API_KEY``            model credential (required to call a provider)
``ASSETFORGE_API_BASE_URL``       OpenAI-compatible base URL of your endpoint
``ASSETFORGE_MODEL``              model id to call
``ASSETFORGE_RUNTIME_ROOT``       directory containing the native runtime package
``ASSETFORGE_RUNTIME_PACKAGE``    that package's importable name, if not discoverable
``ASSETFORGE_RUNTIME_PIN``        identifier of the runtime build the artifacts bind to
``ASSETFORGE_RUNTIME_VENV``       interpreter that has the runtime installed, if any
``ASSETFORGE_MAX_STEPS``          per-task turn budget for the Author
``ASSETFORGE_TIMEOUT_SECONDS``    per-request timeout
``ASSETFORGE_MAX_CONCURRENT``     in-flight tasks

Call :func:`apply` once at process start (the CLI entry points do this) to copy the
operator-facing values onto the internal names the stage modules expect.
"""
from __future__ import annotations

import os

# operator name -> internal name used by the stage modules
_MAP = {
    "ASSETFORGE_API_KEY": ("ASSETFORGE_EVAL_KEY", "EVAL_API_KEY"),
    "ASSETFORGE_API_BASE_URL": ("ASSETFORGE_EVAL_BASE_URL",),
    "ASSETFORGE_MODEL": ("ASSETFORGE_EVAL_MODEL",),
    "ASSETFORGE_TIMEOUT_SECONDS": ("EVAL_REQUEST_TIMEOUT",),
    "ASSETFORGE_MAX_CONCURRENT": ("ASSETFORGE_EVAL_CONCURRENCY",),
}

DEFAULTS = {
    "ASSETFORGE_TIMEOUT_SECONDS": "3600",
    "ASSETFORGE_MAX_STEPS": "50",
    "ASSETFORGE_MAX_CONCURRENT": "32",
}


def value(name: str, default: str | None = None) -> str | None:
    """Read an operator setting, falling back to its documented default."""
    return os.environ.get(name) or DEFAULTS.get(name) or default


def apply() -> None:
    """Copy operator-facing settings onto the internal names the stages read.

    Only sets a variable when it is not already present, so an operator who prefers to set the
    internal name directly is never overridden.
    """
    for public, internals in _MAP.items():
        val = os.environ.get(public)
        if not val:
            continue
        for internal in internals:
            os.environ.setdefault(internal, val)
    # The runtime knobs are read directly by the runtime interface; nothing to copy.
    for name, default in DEFAULTS.items():
        os.environ.setdefault(name, default)


def summary() -> dict:
    """A redacted view of the resolved configuration, safe to log."""
    key = value("ASSETFORGE_API_KEY")
    return {
        "api_key": ("set" if key else "unset"),
        "api_base_url": value("ASSETFORGE_API_BASE_URL", "(provider default)"),
        "model": value("ASSETFORGE_MODEL", "(unset)"),
        "runtime_root": value("ASSETFORGE_RUNTIME_ROOT", "(importable default)"),
        "runtime_pin": value("ASSETFORGE_RUNTIME_PIN", "assetforge-runtime-1"),
        "max_steps": value("ASSETFORGE_MAX_STEPS"),
        "max_concurrent": value("ASSETFORGE_MAX_CONCURRENT"),
        "timeout_seconds": value("ASSETFORGE_TIMEOUT_SECONDS"),
    }
