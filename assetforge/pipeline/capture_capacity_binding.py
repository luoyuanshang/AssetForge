"""Immutable provider capacity binding for the benchmark the frozen release capture-only work.

The binding separates the task-1 Author pool from the migration add-on while
exposing the resulting per-model shared maxima.  It is opt-in so frozen legacy
owners keep their own manifests and cannot be silently changed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BINDING_PATH = ROOT / ".runtime/locks/qa18k_author_provider_slots/capture_capacity_v1.json"
MODELS = ("capture_2", "capture_3", "capture_1")
TASK1 = {"capture_2": 200, "capture_3": 200, "capture_1": 200}
MIGRATION = {"capture_2": 50, "capture_3": 50, "capture_1": 100}
TOTAL = {name: TASK1[name] + MIGRATION[name] for name in MODELS}
BURST = {name: int(TOTAL[name] * 1.2) for name in MODELS}


def value() -> dict:
    raw = BINDING_PATH.read_bytes()
    result = json.loads(raw)
    if result.get("schema_version") != "benchmark-capture-cap-v1":
        raise ValueError("capture capacity binding schema mismatch")
    if result.get("task1_author") != TASK1 or result.get("migration_addon") != MIGRATION:
        raise ValueError("capture capacity binding values mismatch")
    if result.get("shared_model_maximum") != TOTAL or result.get("burst_model_maximum") != BURST or sum(TOTAL.values()) != 800:
        raise ValueError("capture capacity binding total mismatch")
    if result.get("capture_only") is not True:
        raise ValueError("capture capacity binding is not capture-only")
    return result


def enabled() -> bool:
    return os.environ.get("CAPTURE_CAP_BINDING") == "1"


def model_capacity(model: str, *, lane: str = "shared") -> int:
    if model not in MODELS:
        raise ValueError("unknown capture model")
    if not enabled():
        raise ValueError("new capture cap binding is required")
    value()
    if lane == "task1":
        return TASK1[model]
    if lane == "migration":
        return MIGRATION[model]
    if lane == "shared":
        return TOTAL[model]
    if lane == "burst":
        return BURST[model]
    raise ValueError("unknown capture lane")


def reference() -> dict:
    raw = BINDING_PATH.read_bytes()
    value()
    return {"path": str(BINDING_PATH.relative_to(ROOT)),
            "sha256": hashlib.sha256(raw).hexdigest()}
