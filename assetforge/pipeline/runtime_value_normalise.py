"""Normalise values the native runtime hands back into plain JSON-safe Python.

The runtime uses its own model/scalar types.  Anything that needs to be compared, hashed or
written to disk goes through here so the rest of the pipeline can treat values uniformly.
"""
from __future__ import annotations

import json


def normalize_runtime_value(value):
    """Return a plain-Python equivalent of a runtime value."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): normalize_runtime_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [normalize_runtime_value(v) for v in value]
    for attr in ("model_dump", "to_dict", "dict"):
        fn = getattr(value, attr, None)
        if callable(fn):
            try:
                return normalize_runtime_value(fn())
            except Exception:
                pass
    if hasattr(value, "__dict__"):
        try:
            return normalize_runtime_value(
                {k: v for k, v in vars(value).items() if not k.startswith("_")})
        except Exception:
            pass
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)
