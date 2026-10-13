"""Compile an authored task from asset fragments and report all diagnostics."""
from __future__ import annotations

import copy
import json

from .assets import combine_state

FIELDS = {"instruction", "assets", "extra_initial_state", "extra_assertions"}


def compile_task(candidate, *, library, runtime, task_id, seed, business_time):
    diagnostics = []

    def error(pointer, expected, actual, gate="task_format"):
        diagnostics.append({"gate": gate, "pointer": pointer, "expected": expected, "actual": actual})

    if not isinstance(candidate, dict):
        error("/", "task object", type(candidate).__name__)
        return {"passed": False, "diagnostics": diagnostics}
    unknown = set(candidate) - FIELDS
    if unknown:
        error("/", sorted(FIELDS), sorted(candidate))
    instruction = candidate.get("instruction")
    if not isinstance(instruction, str) or not instruction.strip():
        error("/instruction", "nonempty business request", instruction)
    selections = candidate.get("assets")
    if not isinstance(selections, list) or not selections:
        error("/assets", "one or more explicit asset selections", selections)
    extra_state = candidate.get("extra_initial_state", {})
    if not isinstance(extra_state, dict):
        error("/extra_initial_state", "object", type(extra_state).__name__)
    extras = candidate.get("extra_assertions", [])
    if not isinstance(extras, list) or any(not isinstance(a, dict) for a in extras):
        error("/extra_assertions", "list of assertion objects", type(extras).__name__)
    fragments = None
    if isinstance(selections, list) and selections:
        try:
            blueprint, fragments = library.compose(selections, task_id=task_id, seed=seed, business_time=business_time)
        except (ValueError, KeyError, TypeError) as exc:
            error("/assets" + getattr(exc, "pointer", ""),
                  getattr(exc, "expected", "valid parameterized construction"),
                  getattr(exc, "actual", str(exc)), "asset_composition")
            diagnostics[-1]["message"] = str(exc)
    if diagnostics:
        return {"passed": False, "diagnostics": diagnostics}
    try:
        state = combine_state(fragments["world"], extra_state)
    except ValueError as exc:
        error("/extra_initial_state", "nonconflicting asset state", str(exc), "asset_composition")
        return {"passed": False, "diagnostics": diagnostics}
    assertions = copy.deepcopy(fragments["assertions"]) + copy.deepcopy(extras)
    if not assertions:
        error("/assertions", "at least one scorable terminal-state condition", [])
    task = {"task_id": task_id, "instruction": instruction.strip(),
            "initial_state": state, "assertions": assertions}
    try:
        json.dumps(task, allow_nan=False)
    except (ValueError, TypeError) as exc:
        error("/", "finite JSON values", str(exc))
    if not diagnostics:
        native = runtime.compile(copy.deepcopy(task))
        if not isinstance(native, list) or any(not isinstance(row, dict) for row in native):
            raise TypeError("runtime.compile(task) must return a list of diagnostics")
        diagnostics.extend(native)
    return {"passed": not diagnostics, "diagnostics": diagnostics, "task": task,
            "composition": {"blueprint": blueprint, "blueprint_sha256": fragments["blueprint_sha256"],
                            "catalog_sha256": library.sha256, "asset_bindings": fragments["asset_bindings"]},
            "runtime": runtime.describe()}
