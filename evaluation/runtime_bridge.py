"""Bridge from this repository to the external benchmark runtime.

The evaluation driver is the only place in this repository that depends on the benchmark
package.  This module keeps that dependency in one file, so:

* the pipeline stays independent of it;
* the runner gives one clear error when it is absent, instead of an import failure from
  deep inside a library;
* an operator who points at a different build (``ASSETFORGE_RUNTIME_ROOT``) or a different
  pin (``ASSETFORGE_RUNTIME_PIN``) does it here and nowhere else.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# The runtime's importable package name.  Its distribution and module name are the
# operator's choice; we resolve it once, and ASSETFORGE_RUNTIME_PACKAGE short-circuits the
# search when the name is known.
def _candidates():
    """Module names to try, in order: the operator's choice first, then the common ones."""
    names = [os.environ.get("ASSETFORGE_RUNTIME_PACKAGE"), "native_eval_runtime", "automationbench"]
    out = []
    for n in names:
        if n and n not in out:
            out.append(n)
    return tuple(out)
_RESOLVED = {"name": None}


def runtime_package() -> str:
    """Importable name of the benchmark runtime package, resolved once."""
    if _RESOLVED["name"]:
        return _RESOLVED["name"]
    _root()
    import importlib.util
    for name in _candidates():
        if name and importlib.util.find_spec(name) is not None:
            _RESOLVED["name"] = name
            return name
    # not importable: report the preferred name so the error message is actionable
    return _candidates()[0]
DEFAULT_DOMAINS = ("sales", "marketing", "operations", "support", "finance", "hr")

_MISSING = (
    "The benchmark runtime is not importable. This evaluation driver does not reimplement the "
    "benchmark: install the runtime package, or set ASSETFORGE_RUNTIME_ROOT to the directory "
    "that contains it (and optionally ASSETFORGE_RUNTIME_PACKAGE to its module name), then "
    "retry. Tried: {cands}."
)


def runtime_pin() -> str:
    """Identifier of the runtime build this evaluation targets."""
    return os.environ.get("ASSETFORGE_RUNTIME_PIN") or "assetforge-runtime-1"


def _prepend(path: str) -> None:
    p = str(Path(path).resolve())
    if p not in sys.path:
        sys.path.insert(0, p)


def _root() -> None:
    root = os.environ.get("ASSETFORGE_RUNTIME_ROOT")
    if root:
        _prepend(root)


def _import(suffix: str):
    """Import ``<runtime package>.<suffix>``, resolving the package name first."""
    _root()
    pkg = runtime_package()
    module = f"{pkg}.{suffix}" if suffix else pkg
    try:
        return __import__(module, fromlist=["_"])
    except ImportError as exc:
        raise RuntimeError(_MISSING.format(cands=", ".join(_candidates()))
                           + f"  (tried {module!r})") from exc


# --------------------------------------------------------------------------- runtime pieces
def environment_class():
    return _import("runner").AutomationBenchEnv


def create_rubric():
    return _import("rubric").create_rubric()


def domain_dataset(domain: str):
    return _import("domains").get_domain_dataset(domain)


def combined_dataset(domains):
    """The runtime's own dataset object for the given domains (or a concatenation)."""
    dom = _import("domains")
    if hasattr(dom, "get_combined_dataset"):
        return dom.get_combined_dataset(list(domains))
    from datasets import concatenate_datasets
    return concatenate_datasets([dom.get_domain_dataset(d) for d in domains])


def chat_client_class():
    """The runtime's retrying OpenAI-compatible chat client."""
    clients = _import("clients")
    return getattr(clients, "RetryingOpenAIChatCompletionsClient", None) or clients.OpenAIChatCompletionsClient


def responses_client_class():
    clients = _import("clients")
    return getattr(clients, "OpenAIResponsesClient", None)


def client_config(**kwargs):
    """``verifiers.types.ClientConfig`` — the config object the clients accept.

    ``verifiers`` is a separate dependency of the runtime, not a submodule of it, so it is
    imported by its own name.
    """
    try:
        from verifiers.types import ClientConfig
    except ImportError as exc:
        raise RuntimeError(
            "the runtime's client-config dependency ('verifiers') is not importable; install "
            "the runtime package with its dependencies, then retry."
        ) from exc
    return ClientConfig(**kwargs)


def is_available() -> bool:
    try:
        _root()
        import importlib.util
        return any(importlib.util.find_spec(c) is not None for c in _candidates())
    except Exception:
        return False
