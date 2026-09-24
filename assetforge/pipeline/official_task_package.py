"""Author-side tools for official Runtime runtime/scorer task packages.

The agent authors every substantive task decision.  This module only exposes the
public official app/API/assertion contracts on demand and mechanically validates
one new task against the pinned official ``WorldState``, API router and scorer.
It never reads or copies an official benchmark task instance.
"""
from __future__ import annotations

import copy
from collections import Counter, defaultdict
import difflib
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import sys
import traceback
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import quote

from .agentic_runtime_compiler import extract_task_request
from . import native_construction_cases as native_cases
from .assertion_dependency_context import (
    ASSERTION_DEPENDENCY_CONTEXT_CONTRACT,
    assertion_dependency_context,
)
from .official_alignment import (
    PIPELINE_SOURCE_COMMIT,
    PIPELINE_SYSTEM_PROMPT,
    OFFICIAL_RELEASE,
    normalize_runtime_value,
)
from .semantic_task_graph import semantic_graph_to_task_source
from .v9_agentic_rubric_pipeline import validate_candidate_qa_markdown
from .native_validation_cache import evidence_scope, immutable_proof, evidence_statistics


ROOT = Path(__file__).resolve().parents[2]
def _discover_runtime_root():
    """Directory that *contains* the native runtime package, or None when it is not importable.

    Resolved from the imported package so a locally vendored checkout and a pip-installed
    runtime are both handled, and so importing this module never depends on a particular
    filesystem layout.
    """
    override = os.environ.get("ASSETFORGE_RUNTIME_ROOT")
    if override:
        return Path(override)
    try:
        import importlib.util
        spec = importlib.util.find_spec(RUNTIME_PACKAGE)
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.origin:
        return None
    return Path(spec.origin).resolve().parent.parent


from .native_runtime_interface import runtime_package as _runtime_package
RUNTIME_PACKAGE = _runtime_package()
OFFICIAL_ROOT = _discover_runtime_root()
OFFICIAL_PACKAGE_PARENT = OFFICIAL_ROOT


def require_runtime_root():
    """The runtime root, resolved at use time, with one clear error when it is absent."""
    root = OFFICIAL_ROOT or _discover_runtime_root()
    if root is None:
        raise RuntimeError(
            "the native runtime is not importable; install it or set ASSETFORGE_RUNTIME_ROOT, "
            "then retry (the author-side validation needs the runtime's schema, API and scorer)."
        )
    return root
OFFICIAL_TASK_SCHEMA = "agent-authored-official-automation-task-v1"
OFFICIAL_SOURCE_SCHEMA = "agent-authored-official-automation-source-v1"
OFFICIAL_RUNTIME_CONTRACT = "pinned-runtime-world-api-assertion-scorer-v1"
if OFFICIAL_RELEASE == 'the pinned runtime':
    OFFICIAL_RUNTIME_CONTRACT = 'pinned-runtime-world-api-assertion-scorer-v1'
POLICY_FIXTURE_SCORING_CONTRACT = "native-policy-noop-explicit-scoring-guidance-v1"
NATIVE_SEED_READ_WITNESS_CONTRACT = "identity-bound-native-read-record-not-write-provenance-v3"
POLICY_FIXTURE_SCORING_GUIDANCE = (
    "For a public hold/no-op branch, the native scorer normally excludes already-true free "
    "assertions and gives zero credit if no scored assertion remains. Explicitly mark the "
    "genuine public branch outcome excluded=false in both the base assertion and its alternate replacement; "
    "fixture replacements must preserve all assertion fields and scoring flags. Do not add unrelated effects "
    "or remove obligations to obtain credit. This uses the existing native scorer, not a new scoring rule."
)
SCORER_COUNTEREXAMPLE_CONTRACT = (
    "official-runtime-scorer-counterexample-matrix-v7-contract-closure"
)
CONTRACT_CLOSURE_CONTRACT = "official-runtime-scorer-contract-closure-v1"
SCORER_OBLIGATION_KINDS = {
    "required_effect",
    "decision_source",
    "preservation",
    "forbidden_side_effect",
    "identity_or_cardinality",
    "boundary_or_scope",
    "history_or_order",
}
SCORER_OBLIGATION_REQUIRED_KINDS = {
    "required_effect",
    "decision_source",
    "preservation",
    "forbidden_side_effect",
}
SCORER_OBLIGATION_REQUIRED_COUNTEREXAMPLE_FAMILIES = {
    "required_effect": {"required_fact_omission"},
    "decision_source": {"source_corruption", "wrong_witness"},
    "preservation": {"source_corruption", "target_corruption", "scope_violation"},
    "forbidden_side_effect": {
        "duplicate_effect",
        "wrong_target_effect",
        "extra_effect",
        "scope_violation",
    },
    "identity_or_cardinality": {
        "duplicate_effect",
        "wrong_target_effect",
        "wrong_witness",
        "scope_violation",
    },
    "boundary_or_scope": {
        "equivalent_valid_path",
        "boundary_confusion",
        "scope_violation",
    },
    "history_or_order": {
        "equivalent_valid_path",
        "duplicate_effect",
        "source_corruption",
        "target_corruption",
    },
}
SCORER_COUNTEREXAMPLE_EXPECTATIONS = {
    "equivalent_valid_path": True,
    "required_fact_omission": False,
    "boundary_confusion": False,
    "duplicate_effect": False,
    "wrong_target_effect": False,
    "source_corruption": False,
    "extra_effect": False,
    "target_corruption": False,
    "wrong_witness": False,
    "scope_violation": False,
}
SCORER_COUNTEREXAMPLE_START_STATES = {
    "equivalent_valid_path": "initial",
    "required_fact_omission": "initial",
    "boundary_confusion": "initial",
    "wrong_witness": "initial",
    "duplicate_effect": "oracle_complete",
    "wrong_target_effect": "oracle_complete",
    "source_corruption": "oracle_complete",
    "extra_effect": "oracle_complete",
    "target_corruption": "oracle_complete",
    "scope_violation": "oracle_complete",
}
SCORER_COUNTEREXAMPLE_MIN_COUNTS = {
    **{category: 1 for category in SCORER_COUNTEREXAMPLE_EXPECTATIONS},
    "source_corruption": 2,
    "extra_effect": 3,
    "scope_violation": 2,
}
STATE_SURFACE_CLASSIFICATIONS = {
    "required_effect_target",
    "decision_source",
    "protected_non_target",
    "out_of_scope",
}
STATE_SURFACE_TO_OBLIGATION_KIND = {
    "required_effect_target": "required_effect",
    "decision_source": "decision_source",
    "protected_non_target": "preservation",
}


_COMPACT_OFFICIAL_TASK_SOURCE_FIELDS = frozenset(
    {
        "task_instruction",
        "initial_state",
        "assertions",
        "oracle_actions",
        "forbidden_extra_actions",
        "tool_names",
        "selection_contract",
        "policy_fixtures",
        "native_construction_cases",
    }
)

_SIBLING_REPAIR_FIELDS = frozenset({"construction_application_roles", "construction_bindings"})


_SEMANTIC_GRAPH_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "task_instruction",
        "initial_state",
        "oracle_actions",
        "forbidden_extra_actions",
        "tool_names",
        "assertion_nodes",
        "counterexample_nodes",
        "requirement_nodes",
        "out_of_scope_state",
        "closure",
    }
)


def _run_validation_stage(
    stage: str,
    checks: list[tuple[str, Callable[[], None]]],
) -> None:
    """Return all independent failures in one layer instead of one error per model turn."""

    errors: list[dict[str, str]] = []
    for code, check in checks:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - bounded diagnostics for the Author
            errors.append({
                "code": code,
                "error_type": type(exc).__name__,
                "message": str(exc)[:4_000],
            })
    if errors:
        raise _StagedTaskValidationError(stage, errors)


def _require_condition(condition: bool, message: str, error_type: type[Exception] = ValueError) -> None:
    if not condition:
        raise error_type(message)


def _json_pointer_parts(path: str) -> list[str]:
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("repair patch paths must be absolute JSON pointers")
    if path == "/":
        return [""]
    return [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]


def _apply_author_repair_patch(
    document: Mapping[str, Any],
    operations: Any,
    *,
    source_root: str = "task_source",
) -> dict[str, Any]:
    """Apply a bounded RFC-6902 subset to an Author draft, then let full gates revalidate it.

    The controller never invents task semantics.  Every changed value is supplied by the Author;
    this helper merely prevents an unrelated part of a large task package from disappearing while
    one local compiler diagnostic is repaired.
    """

    if not isinstance(operations, list) or not 1 <= len(operations) <= 128:
        raise ValueError("repair_patch must contain 1-128 operations")
    result = copy.deepcopy(dict(document))
    for index, operation in enumerate(operations):
        label = f"repair_patch[{index}]"
        if not isinstance(operation, Mapping) or set(operation) - {"op", "path", "value"}:
            raise ValueError(f"{label} must contain only op, path and optional value")
        op = str(operation.get("op") or "")
        if op not in {"add", "replace", "remove"}:
            raise ValueError(f"{label}.op must be add, replace or remove")
        parts = _json_pointer_parts(str(operation.get("path") or ""))
        if not parts or parts[0] not in {"candidate_markdown", source_root}:
            raise ValueError(
                f"{label}.path must stay inside candidate_markdown or {source_root}"
            )
        if parts[0] == "candidate_markdown" and parts != ["candidate_markdown"]:
            raise ValueError("candidate_markdown repairs must replace the complete Markdown string")
        if op == "remove" and len(parts) <= 2:
            raise ValueError(
                f"repair patch cannot remove the candidate or a top-level {source_root} field"
            )
        parent: Any = result
        for part in parts[:-1]:
            if isinstance(parent, list):
                if not part.isdigit() or int(part) >= len(parent):
                    raise ValueError(f"{label}.path references a missing list index")
                parent = parent[int(part)]
            elif isinstance(parent, Mapping):
                if part not in parent:
                    raise ValueError(f"{label}.path references a missing object key: {part}")
                parent = parent[part]
            else:
                raise ValueError(f"{label}.path traverses a scalar value")
        key = parts[-1]
        if isinstance(parent, list):
            if key == "-":
                if op != "add":
                    raise ValueError(f"{label} may use '-' only with add")
                parent.append(copy.deepcopy(operation.get("value")))
                continue
            if not key.isdigit():
                raise ValueError(f"{label}.path list index must be an integer")
            position = int(key)
            if op == "add":
                if position > len(parent):
                    raise ValueError(f"{label}.path list insertion is out of range")
                parent.insert(position, copy.deepcopy(operation.get("value")))
            elif position >= len(parent):
                raise ValueError(f"{label}.path list index is out of range")
            elif op == "replace":
                parent[position] = copy.deepcopy(operation.get("value"))
            else:
                parent.pop(position)
        elif isinstance(parent, dict):
            if op in {"replace", "remove"} and key not in parent:
                raise ValueError(f"{label}.path references a missing object key: {key}")
            if op == "remove":
                del parent[key]
            else:
                parent[key] = copy.deepcopy(operation.get("value"))
        else:
            raise ValueError(f"{label}.path parent is not a container")
    return result


def _apply_author_repair_fields(
    document: Mapping[str, Any],
    replacements: Any,
    *,
    source_root: str,
) -> dict[str, Any]:
    """Replace complete Author-owned fields without fragile deep JSON-pointer edits.

    Values still come entirely from the Author.  The controller only preserves every
    unmentioned field and restricts edits to explicit top-level semantic boundaries, after
    which the complete native runtime/scorer suite is rerun.
    """

    if not isinstance(replacements, Mapping) or not 1 <= len(replacements) <= 16:
        raise ValueError("repair_fields must contain 1-16 complete field replacements")
    result = copy.deepcopy(dict(document))
    source = result.get(source_root)
    if not isinstance(source, dict):
        raise ValueError(f"repair_fields requires an existing {source_root} draft")
    allowed_source_fields = (
        {
            "task_instruction",
            "initial_state",
            "assertions",
            "oracle_actions",
            "forbidden_extra_actions",
            "scorer_counterexample_tests",
            "scorer_obligation_ledger",
            "state_surface_manifest",
            "contract_closure_manifest",
            "tool_names",
            "selection_contract",
            "policy_fixtures",
            "native_construction_cases",
        }
        if source_root == "task_source"
        else {
            "schema_version",
            "task_instruction",
            "initial_state",
            "assertions",
            "oracle_actions",
            "forbidden_extra_actions",
            "tool_names",
            "assertion_nodes",
            "counterexample_nodes",
            "requirement_nodes",
            "out_of_scope_state",
            "closure",
        }
    )
    for raw_key, value in replacements.items():
        key = str(raw_key or "")
        if key == "candidate_markdown":
            if not isinstance(value, str):
                raise TypeError("repair_fields.candidate_markdown must be a complete string")
            result["candidate_markdown"] = value
            continue
        # Sibling top-level call parameters live next to `task_source`, not inside
        # it.  Measured 2026-09-15: `construction_application_roles` is required
        # by the compile gate but absent from this whitelist, so a submission that
        # got the roles wrong had *no legal syntax* to repair them (8-9% of
        # receipts).  Accept them by name and echo the sub-schema.
        if key in _SIBLING_REPAIR_FIELDS:
            result[key] = copy.deepcopy(value)
            continue
        prefix = f"{source_root}."
        if not key.startswith(prefix):
            raise ValueError(
                f"repair_fields key must be candidate_markdown, "
                f"{' or '.join(sorted(_SIBLING_REPAIR_FIELDS))}, or "
                f"{source_root}.<top-level-field>"
            )
        field = key[len(prefix):]
        if field not in allowed_source_fields:
            raise ValueError(
                f"repair_fields cannot edit nested or unknown field {key!r}; replace its "
                "complete approved top-level field"
            )
        source[field] = copy.deepcopy(value)
    return result


def _fold_provider_flattened_semantic_fields(
    params: Mapping[str, Any],
) -> tuple[dict[str, Any], int]:
    """Losslessly normalize provider-flattened semantic full and repair calls.

    Some OpenAI-compatible providers occasionally emit fields from a nested tool schema as
    sibling function arguments. This accepts only known complete graph fields and only when
    they do not conflict with an already nested value. It never repairs, invents, drops, or
    chooses between competing semantic content.
    """

    normalized = copy.deepcopy(dict(params))
    if "task_source" in normalized:
        raise ValueError("this immutable lineage requires semantic_graph; direct task_source is forbidden")
    if "repair_patch" in normalized:
        raise ValueError(
            "semantic_graph lineage forbids legacy repair_patch; use hash-bound "
            "top-level repair_fields"
        )
    repair_mode = "base_revision_sha256" in normalized or "repair_fields" in normalized
    transformed = 0

    if repair_mode:
        if "semantic_graph" in normalized:
            raise ValueError("repair calls must not mix repairs with a full replacement")
        supplied = normalized.pop("repair_fields", {})
        if not isinstance(supplied, Mapping):
            raise TypeError("repair_fields must be an object")
        replacements: dict[str, Any] = {}

        def add_replacement(key: str, value: Any) -> None:
            nonlocal transformed
            canonical_key = key
            if key in _SEMANTIC_GRAPH_TOP_LEVEL_FIELDS:
                canonical_key = f"semantic_graph.{key}"
                transformed += 1
            if canonical_key == "candidate_markdown":
                pass
            elif canonical_key.startswith("semantic_graph."):
                field = canonical_key.removeprefix("semantic_graph.")
                if field not in _SEMANTIC_GRAPH_TOP_LEVEL_FIELDS:
                    raise ValueError(
                        f"repair_fields cannot edit nested or unknown field {key!r}"
                    )
            else:
                raise ValueError(
                    "repair_fields key must be candidate_markdown or "
                    "semantic_graph.<top-level-field>"
                )
            if canonical_key in replacements and replacements[canonical_key] != value:
                raise ValueError(
                    f"provider-flattened repair field {canonical_key!r} has conflicting values"
                )
            replacements[canonical_key] = copy.deepcopy(value)

        for raw_key, value in supplied.items():
            add_replacement(str(raw_key or ""), value)

        for field in sorted(_SEMANTIC_GRAPH_TOP_LEVEL_FIELDS):
            if field in normalized:
                add_replacement(field, normalized.pop(field))
            dotted = f"semantic_graph.{field}"
            if dotted in normalized:
                add_replacement(dotted, normalized.pop(dotted))
                transformed += 1
        if "candidate_markdown" in normalized:
            add_replacement("candidate_markdown", normalized.pop("candidate_markdown"))
            transformed += 1
        unknown = sorted(set(normalized) - {"base_revision_sha256"})
        if unknown:
            raise ValueError(
                "unsupported semantic tool argument keys: " + ", ".join(unknown)
            )
        normalized["repair_fields"] = replacements
        return normalized, transformed

    flattened = sorted(_SEMANTIC_GRAPH_TOP_LEVEL_FIELDS.intersection(normalized))
    allowed = {"candidate_markdown", "semantic_graph"} | _SEMANTIC_GRAPH_TOP_LEVEL_FIELDS
    unknown = sorted(set(normalized) - allowed)
    if unknown:
        raise ValueError(
            "unsupported semantic tool argument keys: " + ", ".join(unknown)
        )
    if not flattened:
        return normalized, 0
    graph = normalized.get("semantic_graph", {})
    if not isinstance(graph, Mapping):
        raise TypeError("semantic_graph must be an object before folding flattened fields")
    graph = copy.deepcopy(dict(graph))
    for field in flattened:
        sibling_value = normalized.pop(field)
        if field in graph and graph[field] != sibling_value:
            raise ValueError(
                f"provider-flattened semantic field {field!r} conflicts with semantic_graph"
            )
        graph[field] = sibling_value
    normalized["semantic_graph"] = graph
    return normalized, len(flattened)


def _canonicalize_redundant_semantic_graph_projections(
    value: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, int]]:
    """Canonicalize only mechanically redundant semantic-graph projections.

    The Author still owns every state value, assertion, requirement and counterexample.
    This function only removes representations that are provably duplicated by a more
    authoritative location in the same graph, or restores an official WorldState service
    that a provider placed beside ``initial_state``.  Conflicting values remain errors.
    """

    graph = copy.deepcopy(dict(value))
    counts = {
        "world_state_service_fold": 0,
        "scored_out_of_scope_dedup": 0,
        "ledger_empty_binding_object": 0,
    }

    official = _official_imports()
    service_names = {
        str(name) for name in official["WorldState"].model_fields if name != "meta"
    }
    initial_state = graph.get("initial_state")
    if isinstance(initial_state, Mapping):
        canonical_state = copy.deepcopy(dict(initial_state))
        for service in sorted((set(graph) - _SEMANTIC_GRAPH_TOP_LEVEL_FIELDS) & service_names):
            supplied = graph[service]
            if service in canonical_state and canonical_state[service] != supplied:
                continue
            canonical_state.setdefault(service, copy.deepcopy(supplied))
            del graph[service]
            counts["world_state_service_fold"] += 1
        graph["initial_state"] = canonical_state

    requirements = graph.get("requirement_nodes")
    scored_paths: set[str] = set()
    ledger_only = {
        "forbidden_side_effect",
        "identity_or_cardinality",
        "boundary_or_scope",
        "history_or_order",
    }
    if isinstance(requirements, list):
        normalized_requirements = copy.deepcopy(requirements)
        for row in normalized_requirements:
            if not isinstance(row, dict):
                continue
            bindings = row.get("state_bindings")
            if bindings is None and row.get("obligation_kind") in ledger_only:
                row["state_bindings"] = {}
                bindings = {}
                counts["ledger_empty_binding_object"] += 1
            if isinstance(bindings, Mapping):
                scored_paths.update(str(path) for path in bindings)
        graph["requirement_nodes"] = normalized_requirements

    out_of_scope = graph.get("out_of_scope_state")
    if isinstance(out_of_scope, Mapping) and scored_paths:
        canonical_out_of_scope = copy.deepcopy(dict(out_of_scope))
        for state_path in sorted(scored_paths & set(canonical_out_of_scope)):
            del canonical_out_of_scope[state_path]
            counts["scored_out_of_scope_dedup"] += 1
        graph["out_of_scope_state"] = canonical_out_of_scope

    return graph, counts


def _normalize_top_level_action_ledger(
    initial_state: Mapping[str, Any],
) -> tuple[dict[str, Any], int]:
    """Fold a redundant top-level action ledger into official service state.

    Action-only official applications store records at
    ``initial_state.<service>.actions.<action-key>``.  Providers sometimes preserve every
    action key and record but place the shared ``actions`` object one level too high.  The
    service is already encoded losslessly in the dotted action key, so moving that ledger is
    a deterministic structural projection rather than task generation or semantic repair.
    Unknown or conflicting shapes remain untouched and fail the normal WorldState gate.
    """

    state = copy.deepcopy(dict(initial_state))
    actions = state.get("actions")
    if not isinstance(actions, Mapping) or not actions:
        return state, 0
    official_services = {
        str(name)
        for name in _official_imports()["WorldState"].model_fields
        if name != "meta"
    }
    grouped: dict[str, dict[str, Any]] = {}
    for raw_key, rows in actions.items():
        service = _action_ledger_entry_service(raw_key, rows)
        if service not in official_services:
            return state, 0
        grouped.setdefault(service, {})[str(raw_key)] = copy.deepcopy(rows)
    for service, service_actions in grouped.items():
        existing = state.get(service)
        if existing is None:
            state[service] = {"actions": service_actions}
            continue
        if not isinstance(existing, Mapping):
            return copy.deepcopy(dict(initial_state)), 0
        service_state = copy.deepcopy(dict(existing))
        existing_actions = service_state.get("actions")
        if existing_actions is None:
            service_state["actions"] = service_actions
        elif not isinstance(existing_actions, Mapping):
            return copy.deepcopy(dict(initial_state)), 0
        else:
            merged = copy.deepcopy(dict(existing_actions))
            for action_key, rows in service_actions.items():
                if action_key in merged and merged[action_key] != rows:
                    return copy.deepcopy(dict(initial_state)), 0
                merged[action_key] = rows
            service_state["actions"] = merged
        state[service] = service_state
    del state["actions"]
    return state, len(actions)


def _normalize_single_permitted_app_local_state(
    initial_state: Mapping[str, Any],
    permitted_applications: Any,
) -> tuple[dict[str, Any], int]:
    """Wrap an unambiguous app-local state under its sole permitted service.

    ``inspect_official_task_contract`` returns the selected application's local
    schema.  Providers occasionally preserve those exact collection names but
    omit the one outer WorldState service key.  When the frozen pure Author
    Rubric permits exactly one application, no official service key is already
    present, and every supplied key is an actual field of that application's
    Pydantic model, the missing wrapper is a deterministic structural projection.
    Unknown, mixed-service, empty or conflicting shapes remain untouched and fail
    the normal WorldState/application-count gates.
    """

    state = copy.deepcopy(dict(initial_state))
    if not isinstance(permitted_applications, list) or len(permitted_applications) != 1:
        return state, 0
    app = str(permitted_applications[0])
    official = _official_imports()
    WorldState = official["WorldState"]
    service_names = {
        str(name) for name in WorldState.model_fields if str(name) != "meta"
    }
    if app not in service_names or not state:
        return state, 0
    if set(map(str, state)) & service_names:
        return state, 0
    annotation = WorldState.model_fields[app].annotation
    local_fields = {
        str(name) for name in getattr(annotation, "model_fields", {})
    }
    supplied_fields = set(map(str, state))
    if not local_fields or not supplied_fields <= local_fields:
        return state, 0
    return {app: state}, 1


def _is_single_nibble_sha256_typo(supplied: str, expected: str) -> bool:
    return (
        len(supplied) == len(expected) == 64
        and all(char in "0123456789abcdef" for char in supplied.lower())
        and all(char in "0123456789abcdef" for char in expected.lower())
        and sum(
            left != right
            for left, right in zip(supplied.lower(), expected.lower(), strict=True)
        )
        == 1
    )


def _fold_provider_flattened_compact_task_source(
    params: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, int]]:
    """Losslessly restore compact-source fields misplaced by a provider.

    Only known official source fields and official WorldState service names move, and only
    when the canonical destination is absent or byte-equivalent. Conflicts remain visible to
    the normal fail-closed validators.
    """

    normalized = copy.deepcopy(dict(params))
    counts = {
        "bare_repair_field_fold": 0,
        "top_level_source_field_fold": 0,
        "source_service_into_initial_state": 0,
        "initial_state_source_field_unfold": 0,
    }
    repair_mode = "base_revision_sha256" in normalized or "repair_fields" in normalized
    if repair_mode:
        supplied = normalized.get("repair_fields")
        if isinstance(supplied, Mapping):
            replacements: dict[str, Any] = {}
            for raw_key, value in supplied.items():
                key = str(raw_key or "")
                canonical = (
                    f"task_source.{key}"
                    if key in _COMPACT_OFFICIAL_TASK_SOURCE_FIELDS
                    else key
                )
                if canonical != key:
                    counts["bare_repair_field_fold"] += 1
                if canonical in replacements and replacements[canonical] != value:
                    raise ValueError(
                        f"provider-flattened repair field {canonical!r} has conflicting values"
                    )
                replacements[canonical] = copy.deepcopy(value)
            # A provider may flatten complete replacement fields beside
            # repair_fields, or flatten WorldState services beside the explicit
            # replacement initial_state. Move only unambiguous supplied values;
            # never fill missing state from an older draft or overwrite conflict.
            for field in sorted(_COMPACT_OFFICIAL_TASK_SOURCE_FIELDS):
                for key in (field, f"task_source.{field}"):
                    if key not in normalized:
                        continue
                    canonical = f"task_source.{field}"
                    value = normalized.pop(key)
                    if canonical in replacements and replacements[canonical] != value:
                        raise ValueError(f"provider-flattened repair field {canonical!r} has conflicting values")
                    replacements[canonical] = copy.deepcopy(value)
                    counts["top_level_source_field_fold"] += 1
            state = replacements.get("task_source.initial_state")
            if isinstance(state, Mapping):
                state = copy.deepcopy(dict(state))
                services = set(_official_imports()["WorldState"].model_fields) - {"meta"}
                for container in (replacements, normalized):
                    for service in sorted(set(container) & services):
                        supplied_service = container[service]
                        if service in state and state[service] != supplied_service:
                            raise ValueError(f"provider-flattened repair initial_state service {service!r} conflicts")
                        state[service] = copy.deepcopy(supplied_service)
                        del container[service]
                        counts["source_service_into_initial_state"] += 1
                replacements["task_source.initial_state"] = state
            normalized["repair_fields"] = replacements
        return normalized, counts

    source = normalized.get("task_source")
    if not isinstance(source, Mapping):
        return normalized, counts
    source = copy.deepcopy(dict(source))
    for field in sorted(_COMPACT_OFFICIAL_TASK_SOURCE_FIELDS):
        if field not in normalized:
            continue
        sibling = normalized.pop(field)
        if field in source and source[field] != sibling:
            raise ValueError(
                f"provider-flattened task_source field {field!r} has conflicting values"
            )
        source[field] = copy.deepcopy(sibling)
        counts["top_level_source_field_fold"] += 1

    official = _official_imports()
    service_names = {
        str(name) for name in official["WorldState"].model_fields if name != "meta"
    }
    state = source.get("initial_state")
    if isinstance(state, Mapping):
        state = copy.deepcopy(dict(state))
        for field in sorted(_COMPACT_OFFICIAL_TASK_SOURCE_FIELDS - {"initial_state"}):
            if field not in state:
                continue
            misplaced = state[field]
            if field in source and source[field] != misplaced:
                continue
            source.setdefault(field, copy.deepcopy(misplaced))
            del state[field]
            counts["initial_state_source_field_unfold"] += 1
        for service in sorted((set(source) - _COMPACT_OFFICIAL_TASK_SOURCE_FIELDS) & service_names):
            misplaced = source[service]
            if service in state and state[service] != misplaced:
                continue
            state.setdefault(service, copy.deepcopy(misplaced))
            del source[service]
            counts["source_service_into_initial_state"] += 1
        source["initial_state"] = state
    normalized["task_source"] = source
    return normalized, counts


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _serializable_exception_errors(exc: Exception) -> list[Any]:
    """Return structured validator diagnostics without leaking a bound method.

    Pydantic exposes ``ValidationError.errors`` as a method, while the staged
    validator used by this module stores ``errors`` as a list attribute.  The
    former used to be copied verbatim into the tool result, causing the error
    handler's own ``json.dumps`` call to raise and hiding the actionable
    validation failure behind ``builtin_function_or_method is not JSON
    serializable``.  Normalize both shapes and make nested context values JSON
    safe so every rejection remains a repairable, bounded Author diagnostic.
    """

    raw_errors: Any = getattr(exc, "errors", [])
    if callable(raw_errors):
        try:
            raw_errors = raw_errors()
        except Exception as nested_exc:  # pragma: no cover - defensive boundary
            return [{
                "error_type": type(nested_exc).__name__,
                "message": str(nested_exc)[:4_000],
            }]
    if raw_errors in (None, ""):
        return []
    if not isinstance(raw_errors, list):
        raw_errors = [raw_errors]
    return json.loads(json.dumps(raw_errors, ensure_ascii=False, default=str))


class _StagedTaskValidationError(ValueError):
    """One validation layer failed with all independent diagnostics from that layer."""

    def __init__(self, stage: str, errors: list[dict[str, str]]) -> None:
        self.stage = stage
        self.errors = errors
        joined = "; ".join(f"{row['code']}: {row['message']}" for row in errors)
        super().__init__(f"{stage} validation failed: {joined}")


# Stages that run before the first `_official_score` call of the compile turn.
# The queue entry 0004 rule is that a zero-execution static rejection must not
# spend the Author's 1 construction + 2 repair official-regression budget; these
# are the stages where nothing has been executed yet (measured: the first
# `_official_score` is the post-oracle stage).
_ZERO_EXECUTION_STAGES = frozenset({"task_source_structure", "static_native_contract"})



def _validate_private_evidence_gate(profile) -> None:
    """A declared private-evidence minimum must come with the enabled causal gate.

    When `strict_minimum_private_evidence_sources` is set but the causal check is not enabled,
     the run must fail before any provider call.  This is a read-only check over the explicit profile; it is
    never derived from Rubric text.
    """
    if (int((profile or {}).get('strict_minimum_private_evidence_sources', 0)) > 0
            and not (profile or {}).get('strict_named_gate_causal_services')):
        raise ValueError('private evidence source minimum has no enabled causal execution gate')


def _rubric_mechanical_profile(rubric_text: str) -> dict:
    """Deprecated: a Rubric is prose for the Author and never configures a gate.

    2026-09-15 user + supervisor rule (AGENTS.md P0, PROJECT_CONSTRAINTS.md top section):
    no code may derive, write, override or default-backfill profile or gate values from
    Rubric text.  Everything the pipeline enforces is supplied through the explicit
    ``profile_flags`` machine configuration, and a missing key fails closed in the
    consumers.  The only permitted use of the Rubric text is a read-only consistency
    assertion (see ``prepare_parallel_construction_validation.assert_rubric_profile_consistency``).

    The historical implementation parsed English phrases into ``application_count``,
    ``permitted_applications``, ``background_application_allowance`` and a dozen
    ``strict_*`` gates, which meant one sentence in a prompt could switch a gate back on.
    That path is removed; a Rubric that still carries the legacy phrasing is rejected so
    it cannot be silently treated as configuration.
    """
    normalized = ' '.join(str(rubric_text or '').lower().split())
    legacy_phrases = (
        'distinguish necessary effects, necessary evidence, and non-target background',
        'causally necessary simulated applications',
        'assertion-involved applications',
        'background applications (mechanical gate)',
        'private evidence applications whose facts determine a business outcome',
        'three independently decisive private business facts',
        'at least two necessary cross-application joins and one policy exception branch',
    )
    for phrase in legacy_phrases:
        if phrase in normalized:
            raise ValueError(
                'deprecated Author-Rubric derivation: the Rubric may not configure gates '
                '(found %r). Supply every value through explicit profile_flags; the Rubric '
                'is prose and is only read by a read-only consistency assertion.' % phrase)
    return {}


_TASK_QUALITY_GATE_TOKENS = (
    'preservation', 'exactness', 'assertion', 'selection', 'leak', 'sensitivity',
    'distractor', 'hidden', 'semantic',
)


def _gate_class(code: str) -> str:
    """Label a diagnostic as a task-quality check or a construction-protocol check.

    Supervisor 2026-09-15 §97: the two must be told apart in every receipt, because only
    the task-quality ones describe the task the solver will face; the protocol ones only
    describe how we package it.
    """
    text = str(code or '').lower()
    return 'task_quality' if any(token in text for token in _TASK_QUALITY_GATE_TOKENS) else 'construction_protocol'


def _merge_pre_execution_diagnostics(rows):
    """Collapse the same message reported under several codes into one honest diagnostic.

    Measured 2026-09-15: 38 of 51 multi-diagnostic receipts carried one message under both
    ``construction_application_roles`` and ``rubric_mechanical_profile``, so "report every
    failed gate at once" delivered about one real piece of information.

    The merge key is the message text alone.  Stage is deliberately *not* part of the key:
    the direct role check reports under stage ``pre_execution`` while the structural layer
    reports under ``task_source_structure``, so keying on stage kept the same sentence twice
    (user 2026-09-15: two gates must never read the same pair of facts and double-report).
    Every distinct stage is preserved on the merged row instead of being used to split it.
    """
    merged, order = {}, []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get('message') or '')
        code = row.get('code') or row.get('gate') or 'unknown'
        stage = str(row.get('stage') or '')
        if key not in merged:
            entry = dict(row)
            entry['code'] = code
            entry['codes'] = [code]
            entry['stages'] = [stage] if stage else []
            entry['gate_class'] = _gate_class(code)
            merged[key] = entry
            order.append(key)
        else:
            entry = merged[key]
            if code not in entry['codes']:
                entry['codes'].append(code)
            if stage and stage not in entry['stages']:
                entry['stages'].append(stage)
            entry['duplicate_reports'] = int(entry.get('duplicate_reports') or 0) + 1
            if 'task_quality' not in entry.get('gate_class', ''):
                entry['gate_class'] = 'task_quality' if _gate_class(code) == 'task_quality' else entry['gate_class']
    return [merged[key] for key in order]



def _seeded_simulated_application_names(
    initial_state: Mapping[str, Any],
) -> list[str]:
    """Return official application names without mistaking the action ledger for an app.

    Most pinned WorldState services are top-level keys.  Some action-centric official
    integrations instead seed records under ``initial_state.actions.<service>``.  The
    container name ``actions`` is runtime structure, not a simulated application; its
    immediate non-empty children are the corresponding applications.
    """

    applications: set[str] = set()
    for key, value in initial_state.items():
        name = str(key)
        if name in {"meta", "metadata"} or value in ({}, [], None):
            continue
        if name == "actions" and isinstance(value, Mapping):
            for ledger_key, records in value.items():
                if records in ({}, [], None):
                    continue
                applications.add(
                    _action_ledger_entry_service(ledger_key, records)
                    or str(ledger_key)
                )
            continue
        applications.add(name)
    return sorted(applications)


def _action_ledger_entry_service(ledger_key: Any, records: Any) -> str | None:
    """Resolve one action-ledger bucket to its single encoded application."""

    candidates: set[str] = set()
    raw_key = str(ledger_key)
    if "." in raw_key:
        candidates.add(raw_key.split(".", 1)[0])
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, Mapping):
                continue
            action_key = str(record.get("action_key") or "")
            if "." in action_key:
                candidates.add(action_key.split(".", 1)[0])
    return next(iter(candidates)) if len(candidates) == 1 else None


def _seeded_application_state(
    initial_state: Mapping[str, Any], service: str
) -> Any:
    if service in initial_state:
        return initial_state[service]
    actions = initial_state.get("actions")
    if isinstance(actions, Mapping):
        if service in actions:
            return actions.get(service)
        action_rows = {
            str(action_key): value
            for action_key, value in actions.items()
            if str(action_key).split(".", 1)[0] == service
        }
        if action_rows:
            return action_rows
    return None


def _validate_rubric_mechanical_profile(
    *,
    profile: Mapping[str, Any],
    instruction: str,
    initial_state: Any,
    assertions: Any,
    application_roles: Any = None,
) -> None:
    """Fail closed on explicit Rubric bounds before expensive native execution."""

    request_range = profile.get("public_request_char_range")
    if isinstance(request_range, list) and len(request_range) == 2:
        lower, upper = map(int, request_range)
        length = len(instruction)
        if not lower <= length <= upper:
            raise ValueError(
                f"public task request has {length} characters; Author Rubric requires "
                f"{lower}-{upper}"
            )
    request_max = profile.get("public_request_char_max")
    if isinstance(request_max, int) and len(instruction) > request_max:
        raise ValueError(
            f"public task request has {len(instruction)} characters; Author Rubric permits "
            f"at most {request_max}"
        )
    assertion_range = profile.get("assertion_count_range")
    if isinstance(assertion_range, list) and len(assertion_range) == 2 and isinstance(assertions, list):
        lower, upper = map(int, assertion_range)
        if not lower <= len(assertions) <= upper:
            raise ValueError(
                f"task has {len(assertions)} official assertions; Author Rubric requires "
                f"{lower}-{upper}"
            )
    required_apps = profile.get("application_count")
    if profile.get('construction_application_roles'):
        # One declared-role contract, executed exactly once (user + supervisor
        # 2026-09-15 §99/#1).  `compile_and_test_task_package` already runs
        # `validate_roles` as its own `construction_application_roles` check
        # immediately before this stage, over the identical inputs
        # (`initial_state`/`assertions` are the only keys it reads).  Delegating
        # from here re-ran the same function on the same data and reported the
        # same sentence a second time under the code `rubric_mechanical_profile`
        # (measured: identical prose in 51 of 117 run3 receipts, i.e. the top
        # rejection code was one error counted twice).  The declared roles are a
        # strict superset of the legacy seeded-application count below, so they
        # still replace it -- they are simply not re-executed.
        if not isinstance(application_roles, Mapping):
            raise ValueError('bound construction application roles missing')
        return
    if isinstance(required_apps, int) and required_apps > 0 and isinstance(initial_state, Mapping):
        seeded_apps = _seeded_simulated_application_names(initial_state)
        actual = len(seeded_apps)
        for group in profile.get('application_groups_exactly_one', []):
            if len(set(group) & set(seeded_apps)) != 1:
                raise ValueError('Author Rubric requires exactly one application from group: ' + ', '.join(group))
        if "background_application_allowance" not in profile:
            raise ValueError("execution profile is missing background_application_allowance; refusing to default it")
        allowance = int(profile["background_application_allowance"])
        if not required_apps <= actual <= required_apps + allowance:
            raise ValueError(
                f"task seeds {actual} simulated applications; Author Rubric requires exactly "
                f"{required_apps}" + (f" plus at most {allowance} background application(s)" if allowance else "")
            )
        permitted_apps = profile.get("permitted_applications")
        if isinstance(permitted_apps, list) and permitted_apps:
            forbidden_seeded_apps = sorted(set(seeded_apps) - set(permitted_apps))
            if forbidden_seeded_apps:
                raise ValueError(
                    "task seeds simulated applications outside the explicit Author Rubric "
                    f"allowlist: {forbidden_seeded_apps}; permitted={sorted(permitted_apps)}"
                )
        # The 18k distribution contract counts scorer applications from the
        # longest exact seeded-service prefix of every official assertion.  A
        # task that merely seeds four or five services but scores effects in
        # only one to three of them is not a four/five-application scored
        # workflow, even if its prose calls every service causal.  Enforce the
        # same per-item invariant before expensive oracle execution so such a
        # package cannot be materialized and later rejected only by Reviewer or
        # the aggregate distribution gate.  This gate derives no business
        # semantics and invents no assertion; it only checks Author-owned
        # assertions against the explicit pure-Rubric cardinality.
        if isinstance(assertions, list):
            service_fields = sorted(seeded_apps, key=len, reverse=True)
            scored_apps: set[str] = set()
            for assertion in assertions:
                if not isinstance(assertion, Mapping):
                    continue
                assertion_type = str(
                    assertion.get("type") or assertion.get("assertion_type") or ""
                )
                service = next(
                    (
                        field
                        for field in service_fields
                        if assertion_type == field
                        or assertion_type.startswith(field + "_")
                    ),
                    None,
                )
                if service is not None:
                    scored_apps.add(service)
            # A granted background allowance means the extra seeded applications are deliberately
            # NOT scored (that is what makes them distractors); they are excluded from the causal
            # requirement, while every scored application must still appear in the assertions.
            if "background_application_allowance" not in profile:
                raise ValueError("execution profile is missing background_application_allowance; refusing to default it")
            allowance = int(profile["background_application_allowance"])
            background_budget = max(0, allowance)
            missing = sorted(set(seeded_apps) - scored_apps)
            if allowance:
                missing = missing[background_budget:] if len(missing) > background_budget else []
            if missing:
                raise ValueError(
                    "every causally necessary simulated application required by the Author "
                    "Rubric must contribute at least one official assertion; scorer coverage "
                    f"is missing for: {missing}"
                )


def _sha(value: Any) -> str:
    payload = value if isinstance(value, bytes) else _canonical(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _official_imports() -> dict[str, Any]:
    parent = str(OFFICIAL_PACKAGE_PARENT)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    pkg = RUNTIME_PACKAGE
    from importlib import import_module
    if pkg not in sys.modules:
        import_module(pkg)
    module = sys.modules[pkg]
    if OFFICIAL_ROOT is not None:
        expected = OFFICIAL_ROOT / RUNTIME_PACKAGE
        if Path(module.__file__).resolve().parent != expected:
            raise ValueError("the imported runtime is not the one bound by ASSETFORGE_RUNTIME_ROOT")
    rubric = import_module(pkg + ".rubric")
    registry = import_module(pkg + ".rubric.registry")
    world = import_module(pkg + ".schema.world")
    api = import_module(pkg + ".tools.api")
    fetch = import_module(pkg + ".tools.api.fetch")
    search_mod = import_module(pkg + ".tools.api.search")

    create_rubric = rubric.create_rubric
    partial_credit = rubric.partial_credit
    task_completed_correctly = rubric.task_completed_correctly
    AssertionRegistry = registry.AssertionRegistry
    WorldState = world.WorldState
    API_TOOLS = api.API_TOOLS
    api_fetch = api.api_fetch
    _url_to_internal_path = fetch._url_to_internal_path
    _router_service = fetch._router_service
    _compute_url = search_mod._compute_url
    _load_schemas = search_mod._load_schemas

    return {
        "create_rubric": create_rubric,
        "partial_credit": partial_credit,
        "task_completed_correctly": task_completed_correctly,
        "AssertionRegistry": AssertionRegistry,
        "WorldState": WorldState,
        "API_TOOLS": API_TOOLS,
        "api_fetch": api_fetch,
        "url_to_internal_path": _url_to_internal_path,
        "router_service": _router_service,
        "compute_url": _compute_url,
        "load_schemas": _load_schemas,
    }


def _source_contract() -> dict[str, Any]:
    paths = {
        "world_schema": OFFICIAL_ROOT / RUNTIME_PACKAGE / "schema" / "world.py",
        "api_search": OFFICIAL_ROOT / RUNTIME_PACKAGE / "tools" / "api" / "search.py",
        "api_fetch": OFFICIAL_ROOT / RUNTIME_PACKAGE / "tools" / "api" / "fetch.py",
        "assertion_registry": OFFICIAL_ROOT / RUNTIME_PACKAGE / "rubric" / "registry.py",
        "scorer": OFFICIAL_ROOT / RUNTIME_PACKAGE / "rubric" / "__init__.py",
        "runner": OFFICIAL_ROOT / RUNTIME_PACKAGE / "runner.py",
    }
    files = {
        name: {
            "relative_path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for name, path in paths.items()
    }
    return {
        "contract": OFFICIAL_RUNTIME_CONTRACT,
        "source_commit": PIPELINE_SOURCE_COMMIT,
        "files": files,
        "content_sha256": _sha(files),
    }


def official_source_contract():
    """Describe the runtime's source files, resolved on first use.

    Built lazily because a machine without the runtime installed must still be able to import
    this module; only code that actually validates a task needs the contract.
    """
    require_runtime_root()
    return _source_contract()


# Kept as a module attribute for callers that want it eagerly; None until the runtime exists.
OFFICIAL_SOURCE_CONTRACT = None


# One app-only reply carries the whole single-task contract (assertion types, read/write
# field contracts, endpoint parameter contracts) with no truncation.
class OfficialContractInspectorTool:
    """On-demand public contract inspection without exposing benchmark tasks."""

    @staticmethod
    def _native_endpoint_contract(app: str, endpoint: Mapping[str, Any], *, include_source: bool) -> dict[str, Any]:
        """Read the pinned dispatch table; never rewrite its catalog or execute a world.

        The public schema's computed URL can duplicate its base path. Keep that URL
        intact and separately expose only alternatives that the actual dispatch
        table accepts. Exact queries also expose the seed-reading implementation,
        not any benchmark task, task answer, or synthetic QA template.
        """
        official = _official_imports()
        raw_path = str(endpoint.get("native_schema_path") or "")
        documented = str(endpoint.get("url") or "")
        candidates = list(dict.fromkeys([documented, raw_path,
            app + "/" + raw_path.lstrip("/")]))
        matches = []
        for url in candidates:
            # Placeholder substitution is used for matching only, never sent to a provider.
            probe = re.sub(r"\{[^{}]+\}", "1", url)
            path, router = official["url_to_internal_path"](probe)
            if router is None or official["router_service"](router) != app:
                continue
            closure = inspect.getclosurevars(router).nonlocals
            routes, handlers = closure.get("routes", []), closure.get("handlers", {})
            for method, pattern, key in routes:
                if str(method).upper() == str(endpoint.get("method") or "GET").upper() and re.match(pattern, path):
                    handler = handlers.get(key)
                    if callable(handler):
                        matches.append((url, str(pattern), str(key), handler))
                    break  # Same first-match semantics as the fixed router.
        result: dict[str, Any] = {
            "documented_url_matches_native_route": any(m[0] == documented for m in matches),
            "route_verified_url_templates": [m[0] for m in matches],
            "native_route_patterns": list(dict.fromkeys(m[1] for m in matches)),
            "native_handler_keys": list(dict.fromkeys(m[2] for m in matches)),
            "verification_scope": "fixed_native_dispatch_match_not_world_or_scorer_success",
            "world_executed": False,
        }
        if include_source:
            pieces, bindings, seen = [], {}, set()
            queue = [(m[3], 0) for m in matches]
            total = 0
            truncated = False
            while queue:
                function, depth = queue.pop(0)
                if function in seen or not inspect.isfunction(function):
                    continue
                seen.add(function)
                file = Path(inspect.getfile(function)).resolve()
                try:
                    relative = file.relative_to(OFFICIAL_ROOT / RUNTIME_PACKAGE)
                except ValueError:
                    continue
                if relative.parts[0] not in {"tools", "utils", "schema"}:
                    continue
                source = inspect.getsource(function)
                if total + len(source) > 60_000:
                    truncated = True
                    continue
                pieces.append(source)
                total += len(source)
                bindings[str(relative)] = hashlib.sha256(file.read_bytes()).hexdigest()
                if depth < 2:
                    variables = inspect.getclosurevars(function)
                    queue.extend((value, depth + 1) for value in
                        list(variables.globals.values()) + list(variables.nonlocals.values())
                        if inspect.isfunction(value))
            result["implementation_source"] = "\n\n".join(pieces)
            result["source_bindings"] = bindings
            result["source_truncated"] = truncated
        return result

    name = "inspect_official_task_contract"
    description = (
        "Inspect the pinned official Runtime contract for one app. An app-only query "
        "returns a compact index; optionally name one schema_collection, assertion_type, or "
        "endpoint_id to receive that exact contract. This tool never returns benchmark task "
        "instances, initial states or answers."
    )
    parameters = {
        "type": "object",
        "properties": {
            "app": {
                "type": "string",
                "description": "Official WorldState service name, for example slack or hubspot.",
            },
            "assertion_type": {
                "type": "string",
                "description": "Optional exact registered assertion type to inspect.",
            },
            "endpoint_id": {
                "type": "string",
                "description": "Optional exact official endpoint id to inspect in full.",
            },
            "schema_collection": {
                "type": "string",
                "description": (
                    "Optional exact top-level WorldState collection/property to inspect in full."
                ),
            },
        },
        "required": ["app"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        app_catalog_only: bool = False,
        tiered_compact: bool = False,
        allow_exact_queries: bool = False,
    ) -> None:
        if app_catalog_only and tiered_compact:
            raise ValueError("app_catalog_only and tiered_compact are mutually exclusive")
        official = _official_imports()
        WorldState = official["WorldState"]
        self.official_apps = sorted(
            field for field in WorldState.model_fields if field != "meta"
        )
        self.parameters = copy.deepcopy(type(self).parameters)
        self.parameters["properties"]["app"]["enum"] = self.official_apps
        if app_catalog_only and not allow_exact_queries:
            self.parameters["properties"] = {
                "app": self.parameters["properties"]["app"]
            }
        self.call_count = 0
        self.unique_call_count = 0
        self.cache_hit_count = 0
        self.catalog_only_rejection_count = 0
        self._app_catalog_only = app_catalog_only
        self._allow_exact_queries = allow_exact_queries
        self.assertion_dependency_context_contract = (
            ASSERTION_DEPENDENCY_CONTEXT_CONTRACT if allow_exact_queries else None
        )
        self._tiered_compact = tiered_compact
        self.rendered_bytes = 0
        self.app_normalization_count = 0
        self.app_normalization_by_kind: Counter[str] = Counter()
        self._result_by_query: dict[tuple[str, str, str, str], str] = {}

    @staticmethod
    def _compact_schema_annotations(value: Any) -> Any:
        """Remove annotations, never property names or JSON literal data."""
        if isinstance(value, list):
            return [OfficialContractInspectorTool._compact_schema_annotations(v) for v in value]
        if not isinstance(value, Mapping):
            return copy.deepcopy(value)
        result = {}
        for key, child in value.items():
            if key in {"title", "description", "examples"}:
                continue
            if key in {"properties", "$defs", "definitions", "patternProperties", "dependentSchemas"} and isinstance(child, Mapping):
                result[key] = {
                    name: OfficialContractInspectorTool._compact_schema_annotations(schema)
                    for name, schema in child.items()
                }
            elif key in {"const", "default", "enum"}:
                result[key] = copy.deepcopy(child)
            else:
                result[key] = OfficialContractInspectorTool._compact_schema_annotations(child)
        return result

    @staticmethod
    def _schema_references(value: Any) -> set[str]:
        references: set[str] = set()
        if isinstance(value, Mapping):
            reference = value.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/$defs/"):
                references.add(reference.removeprefix("#/$defs/"))
            for child in value.values():
                references.update(OfficialContractInspectorTool._schema_references(child))
        elif isinstance(value, list):
            for child in value:
                references.update(OfficialContractInspectorTool._schema_references(child))
        return references

    @classmethod
    def _schema_fragment(cls, schema: Mapping[str, Any], collection: str) -> dict[str, Any]:
        properties = schema.get("properties") or {}
        if collection not in properties:
            choices = sorted(str(name) for name in properties)
            suggestions = difflib.get_close_matches(collection, choices, n=8, cutoff=0.35)
            raise ValueError(
                f"unknown WorldState collection/property: {collection}; "
                f"closest choices={suggestions}; available choices={choices}"
            )
        root = copy.deepcopy(properties[collection])
        definitions = schema.get("$defs") or {}
        pending = list(cls._schema_references(root))
        selected: dict[str, Any] = {}
        while pending:
            name = pending.pop()
            if name in selected or name not in definitions:
                continue
            selected[name] = copy.deepcopy(definitions[name])
            pending.extend(cls._schema_references(selected[name]) - selected.keys())
        return {
            "collection": collection,
            "schema": root,
            "$defs": selected,
        }

    @classmethod
    def _schema_index(cls, schema: Mapping[str, Any]) -> list[dict[str, Any]]:
        definitions = schema.get("$defs") or {}
        rows: list[dict[str, Any]] = []
        for name, spec in sorted((schema.get("properties") or {}).items()):
            references = sorted(cls._schema_references(spec))
            field_names: set[str] = set()
            for reference in references:
                definition = definitions.get(reference) or {}
                field_names.update(str(key) for key in (definition.get("properties") or {}))
            rows.append(
                {
                    "collection": str(name),
                    "type": spec.get("type") if isinstance(spec, Mapping) else None,
                    "referenced_models": references,
                    "field_names": sorted(field_names),
                }
            )
        return rows

    @staticmethod
    def _collection_field_contracts(schema: Mapping[str, Any]) -> dict[str, Any]:
        """Publish each collection's read/write field contract in the same app reply.

        Measured 2026-09-15 (user ruling, supervisor §99/#3): tiered mode advertised only
        collection names and field names, so the field type/enum/required of a single
        collection still cost one exact ``schema_collection`` query per collection per
        application, and the Author averaged ~22 inspect calls per root.  Publishing the
        contract here removes that second round.  The exact fragments remain available
        (``schema_collection``), so nothing is removed -- only the round is.
        """

        definitions = schema.get("$defs") or {}
        contracts: dict[str, Any] = {}
        for name, spec in sorted((schema.get("properties") or {}).items()):
            reference = ""
            if isinstance(spec, Mapping):
                # A collection is usually a list, so the model reference sits under `items`
                # (e.g. {"type":"array","items":{"$ref":"#/$defs/GmailMessage"}}).  Reading only
                # `$ref` therefore published an empty field list for almost every collection --
                # measured 2026-09-16: `gmail.labels` and `gmail.messages` came back with
                # `legal=[]`, so the Author had no field contract at all and invented fields.
                for candidate in (spec.get("$ref"), (spec.get("items") or {}).get("$ref")
                                  if isinstance(spec.get("items"), Mapping) else None):
                    if isinstance(candidate, str):
                        reference = candidate.rsplit("/", 1)[-1]
                        break
            model = definitions.get(reference) if reference else None
            items_spec = spec.get("items") if isinstance(spec, Mapping) else None
            if not isinstance(model, Mapping):
                model = spec if isinstance(spec, Mapping) else {}
            # A collection may be a free-form object list (gmail.threads is literally
            # {"type":"array","items":{"type":"object","additionalProperties":true}}).  Telling
            # the Author "legal=[]" there is wrong and made the validator flag every field.
            free_form = bool(
                (isinstance(items_spec, Mapping) and items_spec.get("additionalProperties") is True)
                or (isinstance(model, Mapping) and model.get("additionalProperties") is True)
                or not (model.get("properties") if isinstance(model, Mapping) else None))
            if free_form and not reference:
                contracts[str(name)] = {"model": reference, "free_form": True, "fields": {}}
                continue
            required = {str(key) for key in (model.get("required") or [])}
            fields: dict[str, Any] = {}
            for field, field_spec in (model.get("properties") or {}).items():
                if not isinstance(field_spec, Mapping):
                    continue
                row: dict[str, Any] = {}
                if field_spec.get("type"):
                    row["type"] = copy.deepcopy(field_spec["type"])
                if isinstance(field_spec.get("enum"), list):
                    row["enum"] = copy.deepcopy(field_spec["enum"])
                if isinstance(field_spec.get("$ref"), str):
                    row["model"] = str(field_spec["$ref"]).rsplit("/", 1)[-1]
                if isinstance(field_spec.get("items"), Mapping):
                    item = field_spec["items"]
                    row["items"] = {
                        key: copy.deepcopy(item[key])
                        for key in ("type", "enum", "$ref")
                        if key in item
                    }
                if str(field) in required:
                    row["required"] = True
                fields[str(field)] = row
            contracts[str(name)] = {"model": reference, "fields": fields}
        return contracts

    def _app_assertion_names(self, registry: Any, app: str) -> list[str]:
        """Resolve the assertion types owned by one application.

        The default is the pinned name prefix.  ``OwnershipInspector`` overrides this with
        the frozen assertion-ownership map, so the two lineages share one implementation of
        the (large) reply body instead of two divergent copies.
        """

        return sorted(
            name
            for name in registry._handlers  # noqa: SLF001 - pinned public registry
            if name == app or name.startswith(app + "_")
        )

    def call(self, params: Mapping[str, Any] | str, **_: Any) -> str:
        self.call_count += 1
        try:
            value = json.loads(params) if isinstance(params, str) else dict(params)
            raw_app = str(value.get("app") or "").strip()
            normalized_app = re.sub(r"[\s-]+", "_", raw_app.lower())
            app = raw_app
            if raw_app not in self.official_apps and normalized_app in self.official_apps:
                app = normalized_app
                self.app_normalization_count += 1
                kinds: list[str] = []
                if raw_app != raw_app.lower():
                    kinds.append("case")
                if re.search(r"\s", raw_app):
                    kinds.append("space_to_underscore")
                if "-" in raw_app:
                    kinds.append("hyphen_to_underscore")
                self.app_normalization_by_kind[
                    "+".join(kinds) or "canonical_surface"
                ] += 1
            requested = str(value.get("assertion_type") or "").strip()
            requested_endpoint = str(value.get("endpoint_id") or "").strip()
            requested_collection = str(value.get("schema_collection") or "").strip()
            specialized_count = sum(
                bool(item) for item in (requested, requested_endpoint, requested_collection)
            )
            # Exact-enabled Author schemas already expose all three independent
            # selectors. Resolve their bounded same-app fragments together;
            # rejecting that valid shape wasted repeated model/tool rounds.
            # Legacy compact-only lineages retain their original restriction.
            if specialized_count > 1 and not self._allow_exact_queries:
                raise ValueError(
                    "inspect exactly one assertion_type, endpoint_id, or schema_collection per "
                    "query; independent exact queries may be issued together in one tool turn"
                )
            if self._app_catalog_only and not self._allow_exact_queries and specialized_count:
                self.catalog_only_rejection_count += 1
                raise ValueError(
                    "this Author lineage permits only one app-only catalog inspection per "
                    "selected application; the app-only result already contains every legal "
                    "endpoint contract and assertion parameter semantics. Reuse it and copy "
                    "symbols byte-for-byte; do not request assertion_type or endpoint_id"
                )
            query = (app, requested, requested_endpoint, requested_collection)
            if query in self._result_by_query:
                self.cache_hit_count += 1
                prior = self._result_by_query[query]
                # A cache hit must stay self-contained (user ruling 2026-09-15, #3).
                # Returning only a hash is unusable after automatic context compaction:
                # the earlier body may no longer be in the provider-facing view, so the
                # Author had to re-query and could still not read the contract.  The
                # pinned contract is immutable, so the complete prior reply is repeated
                # with the marker every existing consumer already keys on.
                payload = json.loads(prior)
                if not isinstance(payload, dict):
                    payload = {}
                payload["cache_hit"] = True
                payload["query"] = {
                    "app": app,
                    "assertion_type": requested or None,
                    "endpoint_id": requested_endpoint or None,
                    "schema_collection": requested_collection or None,
                }
                payload["prior_result_sha256"] = hashlib.sha256(
                    prior.encode("utf-8")
                ).hexdigest()
                payload["instruction"] = (
                    "Identical query already answered in this root; the complete pinned "
                    "contract is repeated below so a compacted context can still read it. "
                    "Do not issue this query a third time."
                )
                return json.dumps(payload, ensure_ascii=False, sort_keys=True)
            official = _official_imports()
            WorldState = official["WorldState"]
            if app == "meta" or app not in WorldState.model_fields:
                suggestions = difflib.get_close_matches(
                    normalized_app,
                    self.official_apps,
                    n=8,
                    cutoff=0.35,
                )
                raise ValueError(
                    f"unknown official app: {raw_app}; closest official apps={suggestions}; "
                    f"available official apps={self.official_apps}. Copy an exact app from the "
                    "tool schema instead of guessing"
                )
            annotation = WorldState.model_fields[app].annotation
            app_schema = annotation.model_json_schema()
            if self._app_catalog_only:
                app_schema = self._compact_schema_annotations(app_schema)
            schema_index = self._schema_index(app_schema) if self._tiered_compact else []
            selected_schema = (
                self._schema_fragment(app_schema, requested_collection)
                if requested_collection
                else None
            )
            schemas = official["load_schemas"]()
            schema_key = "openai" if app == "chatgpt" else app
            api_schema = schemas.get(schema_key, {})
            endpoints = []
            for endpoint in api_schema.get("endpoints", []):
                row = copy.deepcopy(endpoint)
                native_schema_path = str(row.get("path") or "")
                row["url"] = official["compute_url"](
                    schema_key,
                    str(api_schema.get("baseUrl") or ""),
                    str(row.pop("path", "")),
                )
                if self._allow_exact_queries:
                    row["native_schema_path"] = native_schema_path
                endpoints.append(row)
            endpoint_catalog = []
            for row in endpoints:
                parameter_contract = {}
                for name, spec in (row.get("parameters") or {}).items():
                    if not isinstance(spec, Mapping):
                        continue
                    parameter_contract[str(name)] = {
                        key: copy.deepcopy(spec[key])
                        for key in (
                            "type",
                            "items",
                            "required",
                            "location",
                            "enum",
                            "default",
                        )
                        if key in spec
                    }
                endpoint_row = {
                    "id": row.get("id"),
                    "method": row.get("method"),
                    "url": row.get("url"),
                    "description": str(row.get("description") or "")[:320],
                    "parameters": parameter_contract,
                    "request": row.get("request"),
                }
                if self._tiered_compact:
                    endpoint_row = {
                        "id": row.get("id"),
                        "method": row.get("method"),
                        "url": row.get("url"),
                        # No prose truncation: the working budget is 196,608 estimated
                        # input tokens with a 16,384 reserve, and this reply is the
                        # Author's single per-application contract.  Measured 2026-09-15:
                        # the legacy 160/240-char cuts forced one extra exact query per
                        # collection and per endpoint (~22 inspect calls per root).
                        "description": str(row.get("description") or "")[:320],
                        # Publish the parameter contract, not only the parameter names:
                        # measured Author failures were "the harness dropped my tool
                        # argument" and misspelled locations, which need type/required/
                        # location/enum, and all of them live in this same reply now.
                        "parameters": copy.deepcopy(parameter_contract),
                    }
                if not self._app_catalog_only:
                    if not self._tiered_compact:
                        endpoint_row["response"] = row.get("response")
                if self._allow_exact_queries:
                    endpoint_row["native_execution_contract"] = self._native_endpoint_contract(
                        app, row, include_source=False)
                endpoint_catalog.append(endpoint_row)
            endpoint_ids = [str(row["id"]) for row in endpoint_catalog if row.get("id")]
            selected_endpoints = []
            if requested_endpoint:
                selected_endpoints = [
                    row for row in endpoints if row.get("id") == requested_endpoint
                ]
                if not selected_endpoints:
                    suggestions = difflib.get_close_matches(
                        requested_endpoint,
                        endpoint_ids,
                        n=8,
                        cutoff=0.35,
                    )
                    raise ValueError(
                        f"unknown official endpoint id for app {app}: {requested_endpoint}; "
                        f"closest official endpoint ids={suggestions}; "
                        f"available official endpoint ids={endpoint_ids}. Copy an exact id from "
                        "the app-only catalog instead of guessing"
                    )
                if self._allow_exact_queries:
                    for row in selected_endpoints:
                        row["native_execution_contract"] = self._native_endpoint_contract(
                            app, row, include_source=True)
            registry = official["AssertionRegistry"]
            names = self._app_assertion_names(registry, app)
            assertion_contract_catalog = [
                {
                    "type": name,
                    "public_parameter_semantics": (
                        inspect.getdoc(registry._handlers[name]) or ""
                    )[:2_000],
                }
                for name in names
            ]
            assertion_source = None
            assertion_context = None
            if requested:
                if requested not in names:
                    suggestions = difflib.get_close_matches(
                        requested,
                        names,
                        n=8,
                        cutoff=0.35,
                    )
                    raise ValueError(
                        f"unknown official assertion type for app {app}: {requested}; "
                        f"closest registered types={suggestions}; "
                        f"available registered types={names}. Copy an exact type from the "
                        "app-only catalog instead of guessing"
                    )
                assertion_source = inspect.getsource(registry._handlers[requested])  # noqa: SLF001
                if self._allow_exact_queries:
                    assertion_context = assertion_dependency_context(
                        registry._handlers[requested], package_root=OFFICIAL_ROOT)
            result = {
                "official_contract": {
                    "contract": OFFICIAL_RUNTIME_CONTRACT,
                    "source_commit": PIPELINE_SOURCE_COMMIT,
                    "content_sha256": OFFICIAL_SOURCE_CONTRACT["content_sha256"],
                },
                "app": app,
                "world_state_schema": (
                    app_schema
                    if not self._tiered_compact
                    and not requested
                    and not requested_endpoint
                    and not requested_collection
                    else None
                ),
                "world_state_schema_index": (
                    schema_index
                    if self._tiered_compact
                    and not requested
                    and not requested_endpoint
                    and not requested_collection
                    else []
                ),
                "world_state_collection_contracts": (
                    self._collection_field_contracts(app_schema)
                    if self._tiered_compact
                    and not requested
                    and not requested_endpoint
                    and not requested_collection
                    else {}
                ),
                "requested_world_state_schema": selected_schema,
                "api_endpoint_catalog": (
                    endpoint_catalog
                    if not requested and not requested_endpoint and not requested_collection
                    else []
                ),
                "requested_api_endpoints": selected_endpoints,
                "registered_assertion_types": (
                    names
                    if not requested and not requested_endpoint and not requested_collection
                    else []
                ),
                "assertion_contract_catalog": (
                    assertion_contract_catalog
                    if not requested and not requested_endpoint and not requested_collection
                    else []
                ),
                "requested_assertion_type": requested or None,
                "requested_assertion_handler_source": assertion_source,
                "requested_assertion_dependency_context": assertion_context,
                "requested_endpoint_id": requested_endpoint or None,
                "requested_schema_collection": requested_collection or None,
                # Exact identifier vocabulary, published as flat strings in the
                # artifact the Author already reads.  Measured failure mode: the
                # Author invented collection names, endpoint ids and assertion
                # types ("pages/boards/employees", "slack/conversations.list",
                # "GMAIL_THREAD_REPLY_APPROVED") and burned 25+ inspect rounds per
                # root discovering spellings that the compiler rejects verbatim.
                # This block adds no new permission: it only states the pinned
                # identifiers to copy.
                "identifier_vocabulary": {
                    "world_state_collections": sorted(
                        str(name) for name in (app_schema.get("properties") or {})),
                    "official_endpoint_ids": list(endpoint_ids),
                    "official_assertion_types": list(names),
                    # Scoring capability, published as a plain string so the
                    # Author stops binding necessary scored effects to an
                    # application whose only registered assertions are
                    # ``<app>_action_exists``/``_action_not_exists`` over
                    # ``['actions']`` (notion, basecamp3, recruitee, asana,
                    # monday) or which registers no assertion at all
                    # (facebook_lead_ads, linkedin_conversions, hiver).
                    # Measured failure mode: cells whose permitted applications
                    # were mostly action-only burned every root at compile on
                    # "unknown WorldState collection/property: pages".
                    "scoring_capability": (
                        "action-only: the only registered assertions are "
                        + "/".join(names)
                        + " over the 'actions' collection. This application cannot observe a "
                        "record-state change, so place every necessary scored effect on a "
                        "record-level application in this cell and use this one for "
                        "action-presence scoring or as background / semantic distractor."
                        if names
                        and all(
                            str(name).endswith(("_action_exists", "_action_not_exists"))
                            for name in names
                        )
                        else "background-only: no assertion is registered for this application "
                        "in the pinned official release. It must not carry a necessary scored "
                        "effect; use it only as a background record source or semantic "
                        "distractor."
                        if not names
                        else "record-level: registered assertions observe application records."
                    ),
                    "usage": (
                        "Copy these identifiers exactly into task_source.initial_state, "
                        "oracle_actions and assertions. Do not invent, translate or "
                        "re-capitalise collection names, endpoint ids or assertion types."),
                },
                "tiered_compact": self._tiered_compact,
                "exact_queries_allowed": not self._app_catalog_only or self._allow_exact_queries,
                "benchmark_task_instances_included": False,
                "app_name_normalized": raw_app != app,
                "submitted_app_name": raw_app,
            }
            # No size ceiling: the previous tiered mode truncated long payloads and lost evidence.
            # cut prose to stay under a budget that was set when the compaction point was
            # 65,536 estimated tokens; that budget is now 196,608 and this reply is the
            # Author's complete per-application contract.  Measured: even the largest
            # applications (quickbooks, bamboohr) render below the legacy non-tiered
            # catalog they replaced, and the working context archives oversized tool
            # results by reference instead of dropping them.
            rendered = json.dumps(result, ensure_ascii=False, sort_keys=True)
            self._result_by_query[query] = rendered
            self.unique_call_count += 1
            self.rendered_bytes += len(rendered.encode("utf-8"))
            # Bounded inspection budget: measured production roots spent up to
            # 38 inspect calls per root while the construction/compile gates were
            # still untouched.  After a small number of contract rounds the
            # binding constraint is no longer contract knowledge, so every later
            # reply carries an explicit directive to move on.  This adds
            # instruction, never removes a requirement or an evidence gate.
            if self.call_count > 6:
                try:
                    payload = json.loads(rendered)
                except ValueError:
                    payload = None
                if isinstance(payload, dict):
                    payload["inspection_budget"] = {
                        "calls_used": self.call_count,
                        "unique_queries": self.unique_call_count,
                        "directive": (
                            "Contract inspection is no longer the limiting step. Stop querying new "
                            "fragments unless one exact fact is genuinely missing: copy names from "
                            "identifier_vocabulary (world_state_collections / official_endpoint_ids / "
                            "official_assertion_types) instead of re-querying, then proceed with "
                            "construct_business_assets(describe -> instantiate) and "
                            "compile_and_test_task_package. Repeated whole-app catalog reads do not "
                            "produce QA."),
                    }
                    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
            return rendered
        except Exception as exc:  # noqa: BLE001 - model receives a bounded correction
            return json.dumps(
                {"accepted": False, "error_type": type(exc).__name__, "error": str(exc)[:12_000]},
                ensure_ascii=False,
            )


def _service_for_contract_name(name: str, service_fields: list[str]) -> str | None:
    for field in service_fields:
        if name == field or name.startswith(field + "_"):
            return field
    return None


def _compute_allowed_services(
    *,
    initial_state: dict[str, Any],
    assertions: list[dict[str, Any]],
    tool_names: list[str],
    service_fields: list[str],
) -> list[str]:
    """Exact local rendering of the pinned runner's service-derivation rule.

    Importing ``runtime.runner`` requires its optional ``verifiers`` execution
    dependency.  Author workers only need the deterministic contract calculation, whose
    implementation is hash-bound through :data:`OFFICIAL_SOURCE_CONTRACT`.
    """

    initial_state = normalize_runtime_value(initial_state)
    allowed = {key for key in initial_state if key != "meta" and key in service_fields}
    for assertion in assertions:
        service = _service_for_contract_name(str(assertion.get("type") or ""), service_fields)
        if service:
            allowed.add(service)
    for tool_name in tool_names:
        service = _service_for_contract_name(tool_name, service_fields)
        if service:
            allowed.add(service)
    return sorted(allowed)


def _official_task_compatibility_check(task: dict[str, Any]) -> dict[str, Any]:
    official = _official_imports()
    if task.get("prompt") != [
        {"role": "system", "content": PIPELINE_SYSTEM_PROMPT},
        {"role": "user", "content": task["prompt"][1]["content"]},
    ]:
        raise ValueError("task prompt does not use the exact official system/user layout")
    WorldState = official["WorldState"]
    world = WorldState(**normalize_runtime_value(copy.deepcopy(task["info"]["initial_state"])))
    service_fields = sorted(
        (str(field) for field in WorldState.model_fields if field != "meta"),
        key=len,
        reverse=True,
    )
    allowed_services = _compute_allowed_services(
        initial_state=task["info"]["initial_state"],
        assertions=task["info"]["assertions"],
        tool_names=task["info"]["tool_names"],
        service_fields=service_fields,
    )
    world.meta.allowed_services = allowed_services
    tool_names = [tool.__name__ for tool in official["API_TOOLS"]]
    if tool_names != ["api_search", "api_fetch", "base64_encode"]:
        raise ValueError(f"official api tool surface mismatch: {tool_names}")
    return {
        "task_shape_validated": True,
        "world_state_validated": True,
        "tool_names": tool_names,
        "verification_gate": False,
        "recovery_gate": False,
        "allowed_services": allowed_services,
    }


def _official_score(*, initial_state: dict[str, Any], assertions: list[dict[str, Any]], world: Any) -> dict[str, Any]:
    official = _official_imports()
    state = {
        "info": {"assertions": [normalize_runtime_value(copy.deepcopy(a)) for a in assertions]},
        "initial_state": normalize_runtime_value(copy.deepcopy(initial_state)),
        "world": world,
    }
    partial = float(official["partial_credit"](state))
    strict = bool(official["task_completed_correctly"](state))
    return {
        "partial_credit": partial,
        "strict_pass": strict,
        "assertion_results": copy.deepcopy(state.get("_assertion_results") or []),
    }


def _recorded_action_candidates(
    *,
    world: Any,
    assertions: list[dict[str, Any]],
    service_fields: list[str],
) -> list[dict[str, Any]]:
    """Project exact runtime action records needed to repair action assertions.

    Generic ``*_action_exists`` assertions match the runtime action log, not arbitrary
    business fields from the seeded record. Returning the exact recorded parameter surface
    is a diagnostic only: it neither adds assertions nor changes the authored task. This keeps
    the Author as the semantic owner while avoiding repeated guesses about a mechanical duplicate
    of an already executed oracle action.
    """

    requested: set[tuple[str, str]] = set()
    for assertion in assertions:
        assertion_type = str(assertion.get("type") or "")
        if not re.fullmatch(r"[a-z0-9_]+_action_(?:not_)?exists", assertion_type):
            continue
        service = _service_for_contract_name(assertion_type, service_fields)
        action_key = str(assertion.get("action_key") or "")
        if service and action_key:
            requested.add((service, action_key))

    output: list[dict[str, Any]] = []
    for service, action_key in sorted(requested):
        app_state = getattr(world, service, None)
        action_map = getattr(app_state, "actions", None)
        if not isinstance(action_map, Mapping):
            continue
        records = action_map.get(action_key)
        if not isinstance(records, list) or not records:
            output.append({
                "service": service,
                "requested_action_key": action_key,
                "exact_record_count": 0,
                "available_action_keys": sorted(str(key) for key in action_map)[:32],
            })
            continue
        projected_records: list[dict[str, Any]] = []
        for record in records[:4]:
            raw = (
                record.model_dump(mode="json")
                if hasattr(record, "model_dump")
                else copy.deepcopy(record)
            )
            if isinstance(raw, Mapping):
                params = raw.get("params")
                if isinstance(params, Mapping):
                    projected_records.append(copy.deepcopy(dict(params)))
        output.append({
            "service": service,
            "requested_action_key": action_key,
            "exact_record_count": len(records),
            "recorded_params": projected_records,
        })
    return output


def _world_content_sha256(world: Any) -> str:
    return _sha(world.model_dump(mode="json"))


def _changed_leaf_paths(before: Any, after: Any, prefix: str = "$") -> set[str]:
    """Return deterministic JSON-style paths changed by one executable probe.

    The result deliberately describes only structure, never field values.  It lets the
    compiler reject cosmetically different counterexamples that mutate the same state
    surface, while keeping task contents and hidden answers out of receipts.
    """

    if type(before) is not type(after):  # noqa: E721 - exact JSON container type matters
        return {prefix}
    if isinstance(before, Mapping):
        changed: set[str] = set()
        for key in sorted(set(before) | set(after), key=str):
            child = f"{prefix}.{key}"
            if key not in before or key not in after:
                changed.add(child)
            else:
                changed.update(_changed_leaf_paths(before[key], after[key], child))
        return changed
    if isinstance(before, list):
        changed = set()
        common = min(len(before), len(after))
        for index in range(common):
            changed.update(
                _changed_leaf_paths(before[index], after[index], f"{prefix}[{index}]")
            )
        for index in range(common, max(len(before), len(after))):
            changed.add(f"{prefix}[{index}]")
        return changed
    return set() if before == after else {prefix}


def _changed_scalar_token_paths(
    before: Any,
    after: Any,
    path: tuple[str | int, ...] = (),
) -> list[tuple[tuple[str | int, ...], Any]]:
    """Return changed scalar leaves, expanding newly created records field by field."""

    missing = object()
    if isinstance(after, Mapping):
        left = before if isinstance(before, Mapping) else {}
        rows: list[tuple[tuple[str | int, ...], Any]] = []
        for key in sorted(after, key=str):
            rows.extend(
                _changed_scalar_token_paths(
                    left.get(key, missing), after[key], (*path, str(key))
                )
            )
        return rows
    if isinstance(after, list):
        left = before if isinstance(before, list) else []
        rows = []
        for index, value in enumerate(after):
            prior = left[index] if index < len(left) else missing
            rows.extend(_changed_scalar_token_paths(prior, value, (*path, index)))
        return rows
    if before is not missing and type(before) is type(after) and before == after:
        return []
    return [(path, after)] if after is not None else []


def _action_controlled_scalars(actions: list[dict[str, Any]]) -> set[tuple[str, str]]:
    controls: set[tuple[str, str]] = set()

    def walk(value: Any, field: str = "") -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                walk(child, str(key))
        elif isinstance(value, list):
            for child in value:
                walk(child, field)
        elif field and value is not None:
            controls.add(
                (re.sub(r"[^a-z0-9]", "", field.casefold()), _canonical(value))
            )

    for action in actions:
        if str(action.get("method") or "GET").upper() in {"GET", "HEAD", "OPTIONS"}:
            continue
        for container in (action.get("params"), action.get("body")):
            value = container
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    continue
            walk(value)
    return controls


def _counterfactual_scalar(value: Any) -> Any | None:
    if value is None:
        return "counterfactual-null-replacement"
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 7919
    if isinstance(value, float):
        return value + 7919.125
    if not isinstance(value, str) or not value:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return "2099-12-31" if value != "2099-12-31" else "2000-01-01"
    if "@" in value and re.fullmatch(r"[^@\s]+@[^@\s]+", value):
        return "counterfactual@example.com"
    return (
        "counterfactual-value"
        if value != "counterfactual-value"
        else "alternate-value"
    )


def _token_path_value(
    value: Any,
    path: tuple[str | int, ...],
    *,
    missing: Any,
) -> Any:
    current = value
    try:
        for token in path:
            current = current[token]
    except (KeyError, IndexError, TypeError):
        return missing
    return current


def _counterfactual_scalar_candidates(
    value: Any,
    *,
    preferred: Iterable[Any] = (),
) -> list[Any]:
    """Return bounded, schema-friendly alternatives for one scalar.

    Values already present in the same typed state surface come first.  They are
    substantially more useful than a synthetic sentinel for enum fields.  Text
    polarity is not changed here because a public requirement may intentionally
    permit harmless surrounding prose around an atomic marker.
    """

    candidates = list(preferred)
    synthetic = _counterfactual_scalar(value)
    if synthetic is not None:
        candidates.append(synthetic)
    unique: list[Any] = []
    seen = {_canonical(value)}
    for candidate in candidates:
        if type(candidate) is not type(value) and not (value is None and candidate is not None):
            continue
        encoded = _canonical(candidate)
        if encoded in seen:
            continue
        seen.add(encoded)
        unique.append(candidate)
    return unique[:8]


def _set_token_path(value: Any, path: tuple[str | int, ...], replacement: Any) -> None:
    parent = value
    for token in path[:-1]:
        parent = parent[token]
    parent[path[-1]] = replacement


def _set_token_path_allow_new_leaf(
    value: Any,
    path: tuple[str | int, ...],
    replacement: Any,
) -> None:
    """Set an existing path or add its final mapping leaf, never inventing parents."""

    parent = value
    for token in path[:-1]:
        parent = parent[token]
    final = path[-1]
    if isinstance(parent, Mapping) and isinstance(final, str):
        parent[final] = replacement
        return
    parent[final] = replacement


def _absolute_state_path_tokens(path: str) -> tuple[str | int, ...]:
    if not isinstance(path, str) or not path.startswith("$."):
        raise ValueError(f"state path must start with '$.': {path!r}")
    tokens: list[str | int] = []
    position = 1
    while position < len(path):
        if path[position] == ".":
            match = re.match(r"\.([A-Za-z_][A-Za-z0-9_]*)", path[position:])
            if not match:
                raise ValueError(f"invalid state path token at {path[position:]!r}")
            tokens.append(match.group(1))
            position += len(match.group(0))
            continue
        if path[position] == "[":
            match = re.match(r"\[(\d+)\]", path[position:])
            if not match:
                raise ValueError(f"state path indices must be zero-based integers: {path!r}")
            tokens.append(int(match.group(1)))
            position += len(match.group(0))
            continue
        raise ValueError(f"invalid state path token at {path[position:]!r}")
    if not tokens:
        raise ValueError("state path must identify one scalar leaf")
    return tuple(tokens)


def _selection_predicate_matches(value: Any, operator: str, expected: Any) -> bool:
    if operator == "eq":
        return type(value) is type(expected) and value == expected
    if operator == "ne":
        return not (type(value) is type(expected) and value == expected)
    if operator in {"gt", "gte", "lt", "lte"}:
        if isinstance(value, bool) or isinstance(expected, bool):
            raise TypeError(f"operator {operator} does not accept booleans")
        if not isinstance(value, (int, float, str)) or not isinstance(
            expected, type(value)
        ):
            raise TypeError(f"operator {operator} requires same-typed ordered scalars")
        return {
            "gt": value > expected,
            "gte": value >= expected,
            "lt": value < expected,
            "lte": value <= expected,
        }[operator]
    if operator == "contains":
        if isinstance(value, str) and isinstance(expected, str):
            return expected in value
        if isinstance(value, list):
            return expected in value
        raise TypeError("operator contains requires text or a list")
    raise ValueError(f"unsupported selection predicate operator: {operator!r}")


def _execute_official_action_sequence(
    *,
    official: Mapping[str, Any],
    world: Any,
    actions: list[dict[str, Any]],
    label: str,
) -> tuple[list[dict[str, Any]], int]:
    """Execute one author-supplied test sequence without inventing task semantics."""

    receipts: list[dict[str, Any]] = []
    state_changing_calls = 0
    for index, action in enumerate(actions):
        if not isinstance(action, Mapping):
            raise ValueError(f"{label}.actions[{index}] must be an object")
        if set(action) - {"method", "url", "params", "body"}:
            raise ValueError(f"{label}.actions[{index}] has unsupported keys")
        method = str(action.get("method") or "GET").upper()
        url = str(action.get("url") or "")
        if not url:
            raise ValueError(f"{label}.actions[{index}].url is required")
        params_value = action.get("params")
        body_value = action.get("body")
        params_text = (
            _canonical(params_value)
            if isinstance(params_value, Mapping)
            else params_value
        )
        body_text = (
            _canonical(body_value)
            if isinstance(body_value, Mapping)
            else body_value
        )
        before_business=world.model_dump(mode='json');before_business.pop('meta',None)
        response_text = official["api_fetch"](
            world,
            method,
            url,
            params=params_text,
            body=body_text,
        )
        after_business=world.model_dump(mode='json');after_business.pop('meta',None)
        changed_applications=sorted(k for k in set(before_business)|set(after_business)
                                    if before_business.get(k)!=after_business.get(k))
        try:
            response_value = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{label}.actions[{index}] returned non-JSON"
            ) from exc
        if (
            isinstance(response_value, dict)
            and response_value.get("error") is not None
        ):
            raise ValueError(
                f"{label}.actions[{index}] is not executable: "
                + _canonical(response_value)[:6_000]
            )
        state_changing_calls += int(bool(changed_applications))
        receipts.append({
            "state_changing":bool(changed_applications),
            "changed_applications":changed_applications,
            "index": index,
            "method": method,
            "url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
            "response_sha256": hashlib.sha256(
                response_text.encode("utf-8")
            ).hexdigest(),
        })
    return receipts, state_changing_calls


def _validate_compact_google_sheets_write_surface(
    actions: list[dict[str, Any]],
) -> None:
    """Keep compact tasks on Sheets effects the official scorer can close.

    The pinned registry can observe exact cell/row state, but worksheet structure
    has only an existence predicate.  A worksheet rename/create/delete can
    therefore be satisfied by changing the wrong tab or by adding another tab.
    Compact Author lineages must use the values surface for durable Sheets writes.
    """

    for index, action in enumerate(actions):
        method = str(action.get("method") or "GET").upper()
        url = str(action.get("url") or "")
        if method in {"GET", "HEAD", "OPTIONS"}:
            continue
        if "sheets.googleapis.com/" not in url.casefold():
            continue
        if "/values/" in url or "/values:" in url:
            continue
        raise ValueError(
            f"oracle_actions[{index}] uses a Google Sheets structural write that the pinned "
            "official scorer cannot close by stable worksheet identity and exact worksheet "
            "cardinality; use an exact cell/row values operation or redesign the effect"
        )


def _validate_native_action_guard_representation(assertions, initial_state):
    """Replay known native action identities instead of trusting parameter spelling.

    Bounded regression for the Airtable/Drive mismatches independently reproduced
    by Reviewer. This is not a claim of exhaustive guard coverage for all apps.
    No candidate, official handler or assertion is rewritten.
    """
    guards = [a for a in assertions if isinstance(a, dict)
              and a.get('type') in {'airtable_action_not_exists', 'google_drive_action_not_exists'}
              and a.get('excluded') is not True and a.get('scored') is not False]
    if not guards:
        return
    official = _official_imports()
    errors = []
    for index, guard in enumerate(guards):
        service = guard['type'].removesuffix('_action_not_exists')
        key = guard.get('action_key')
        params = guard.get('params') or {}
        if not isinstance(params, dict):
            continue  # The general assertion-shape check reports this.
        if service == 'google_drive' and key in {'deleteFile', 'delete_file'}:
            if key != 'delete_file' or 'fileId' in params:
                errors.append('Drive DELETE records delete_file with parameter file (file_id is an official alias); deleteFile/fileId do not match')
                continue
            file_id = params.get('file', params.get('file_id'))
            if not isinstance(file_id, str) or not file_id:
                continue
            cases = [('DELETE', f'https://www.googleapis.com/drive/v3/files/{file_id}', None)]
        elif service == 'airtable' and key in {'createRecord', 'create_record', 'updateRecord', 'update_record'}:
            if set(params) & {'baseId', 'tableId'}:
                errors.append('Airtable native action params are applicationId/tableName, not baseId/tableId; recordId and fields retain their native names')
                continue
            base_id, table_id = params.get('applicationId'), params.get('tableName')
            if not isinstance(base_id, str) or not isinstance(table_id, str):
                continue
            aliases = {table_id}
            seeded_table = None
            for base in initial_state.get('airtable', {}).get('bases', []):
                if base.get('id') == base_id:
                    for table in base.get('tables', []):
                        if table_id in {table.get('id'), table.get('name')}:
                            seeded_table = table
                            aliases.update(v for v in (table.get('id'), table.get('name')) if isinstance(v, str) and v)
            body = {'fields': copy.deepcopy(params.get('fields') or {'native_guard_probe': 'extra'})}
            update = key in {'updateRecord', 'update_record'}
            record = params.get('recordId')
            if update and not isinstance(record, str):
                continue
            # A guard may concern a record created later by the oracle. Do not
            # invent that record or call a failed initial-state probe coverage.
            if seeded_table is None or (update and not any(
                row.get('id') == record for row in seeded_table.get('records', [])
            )):
                continue
            cases = [('PATCH' if update else 'POST',
                      f'https://api.airtable.com/v0/{base_id}/{quote(alias, safe="")}' + (f'/{record}' if update else ''),
                      body) for alias in sorted(aliases)]
        else:
            continue
        for method, url, body in cases:
            world = official['WorldState'](**normalize_runtime_value(copy.deepcopy(initial_state)))
            world.meta.allowed_services = [key for key in initial_state if key != 'meta']
            # An unrelated guard already false in the seed cannot mask the
            # missing coverage. Only a true -> false transition is evidence.
            matching = [a for a in guards if a['type'] == guard['type']
                        and official['AssertionRegistry'].check(world, a)]
            response = json.loads(official['api_fetch'](world, method, url,
                body=_canonical(body) if body is not None else None))
            if isinstance(response, dict) and response.get('error'):
                errors.append(f'{service} guard probe could not execute its claimed native operation: {response["error"]}')
                continue
            if all(official['AssertionRegistry'].check(world, a) for a in matching):
                errors.append(f'{service} public action guard remains true after native {method} at {url}; cover real parameter names and every seeded ID/name identity without widening the public scope')
    if errors:
        raise ValueError('; '.join(dict.fromkeys(errors)))


def _run_policy_fixtures(*, initial_state, assertions, oracle_actions, fixtures,
                         allowed_services, instruction, minimum_count=1,
                         require_independent_readable_facts=False, maximum_count=4,
                         require_five_app_dependencies=False, require_single_scalar_dependency=False,
                         native_fact_json_projection=False, require_coordinated_status=False,
                         require_hr_fiveapp_conditions=False, require_marketing_fiveapp_conditions=False,
                         require_sales_fiveapp_conditions=False, application_roles=None,
                         minimum_role_join_pairs=0):
    """Independently reset a changed-policy case, without duplicating the base world.

    All edits and alternate actions are authored, never synthesized by the gate.
    These are private construction tests, not extra solver messages or scored QA.
    The two correct paths must fail under the other world's expected outcome.
    Semantic fidelity to the same public policy remains an independent review duty.
    """
    if type(maximum_count) is not int or not 1 <= maximum_count <= 12:
        raise ValueError("policy fixture maximum must be an explicit bounded integer 1-12")
    if type(minimum_count) is not int or not 1 <= minimum_count <= maximum_count:
        raise ValueError(f"policy fixture minimum must be 1-{maximum_count}")
    if not isinstance(fixtures, list) or not minimum_count <= len(fixtures) <= maximum_count:
        raise ValueError(f"policy_fixtures requires {minimum_count}-{maximum_count} independently reset cases")
    official = _official_imports()
    WorldState = official["WorldState"]
    dependency_witnesses = None
    if minimum_role_join_pairs:
        if require_five_app_dependencies or not application_roles:
            raise ValueError('role-aware joins need an explicit separate role contract')
        from .multi_app_policy_dependencies import validate
        dependency_witnesses=validate(initial_state=initial_state,fixtures=fixtures,oracle_actions=oracle_actions,
            allowed_services=allowed_services,official=official,pointer_parts=_json_pointer_parts,canonical=_canonical,
            required_services=application_roles['necessary_applications'],minimum_relationship_pairs=minimum_role_join_pairs,
            require_all_services=False,native_reads_by_effect=True,allow_business_keys=True)
    if require_five_app_dependencies:
        if require_independent_readable_facts:
            raise ValueError('single-app and five-app dependency profiles cannot be combined')
        from .multi_app_policy_dependencies import validate
        dependency_witnesses = validate(initial_state=initial_state, fixtures=fixtures,
            oracle_actions=oracle_actions, allowed_services=allowed_services,
            official=official, pointer_parts=_json_pointer_parts, canonical=_canonical,
            require_single_scalar=require_single_scalar_dependency)
    fact_witnesses = None
    condition_profiles = (require_hr_fiveapp_conditions, require_marketing_fiveapp_conditions,
                          require_sales_fiveapp_conditions)
    if sum(bool(value) for value in condition_profiles) > 1:
        raise ValueError('two different five-app condition contracts cannot be combined')
    if any(condition_profiles) and (require_independent_readable_facts or require_five_app_dependencies):
        raise ValueError('HR condition profile cannot mix unrelated fixture contracts')
    if require_independent_readable_facts or any(condition_profiles):
        from .single_app_policy_facts import validate
        fact_witnesses = validate(initial_state=initial_state, fixtures=fixtures,
            oracle_actions=oracle_actions, allowed_services=allowed_services,
            instruction=instruction, official=official, pointer_parts=_json_pointer_parts,
            canonical=_canonical,native_json_projection=native_fact_json_projection,
            hr_fiveapp_conditions=require_hr_fiveapp_conditions,
            marketing_fiveapp_conditions=require_marketing_fiveapp_conditions,
            sales_fiveapp_conditions=require_sales_fiveapp_conditions)
    results = []
    seen_states = set()
    cohort=None;seen_vectors=set()
    if require_coordinated_status:
        from .marketing_coordinated_status import validate as validate_cohort
        cohort=validate_cohort(initial_state,assertions,actions=oracle_actions)
        seen_vectors.add(tuple(cohort['status_vector']))
    for index, row in enumerate(fixtures):
        label = f"policy_fixtures[{index}]"
        keys = {"public_policy_basis", "initial_state_replacements",
                "assertion_replacements", "oracle_actions"}
        if require_five_app_dependencies or minimum_role_join_pairs:
            keys.add('join_witness')
        if not isinstance(row, dict) or set(row) != keys:
            actual_keys = sorted(row) if isinstance(row, Mapping) else None
            raise ValueError(
                f"{label} must contain exactly {sorted(keys)}; "
                f"this row has {actual_keys}; "
                f"missing={sorted(keys - set(row)) if isinstance(row, Mapping) else None}, "
                f"unexpected={sorted(set(row) - keys) if isinstance(row, Mapping) else None}"
            )
        try:
            basis = native_cases.resolve_public_basis(row["public_policy_basis"], instruction,
                label='actual public policy')
        except ValueError as exc:
            raise ValueError(f"{label}.public_policy_basis {exc}") from exc
        replacements = row["initial_state_replacements"]
        if not isinstance(replacements, dict) or not 1 <= len(replacements) <= 16:
            raise ValueError(f"{label} needs 1-16 existing private scalar replacements")
        alt_state = copy.deepcopy(initial_state)
        for pointer, value in replacements.items():
            try:
                parts = _json_pointer_parts(pointer)
            except ValueError as exc:
                # This parser is shared with repair_patch, but the failed field
                # here belongs to a policy fixture. Naming the other API led
                # Authors to repeatedly repair assertions instead of this path.
                # Keep validation unchanged; do not silently translate JSONPath.
                raise ValueError(
                    f"{label}.initial_state_replacements has invalid path {pointer!r}; "
                    "use an absolute RFC 6901 JSON pointer rooted at the service "
                    "inside initial_state (for example /service/collection/0/field), "
                    "not JSONPath/dotted notation. Replace task_source.policy_fixtures "
                    "via repair_fields while keeping its other contents; this is not "
                    "an error in repair_fields key syntax or in assertions."
                ) from exc
            if len(parts) < 2 or parts[0] not in allowed_services:
                raise ValueError(f"{label} replacement must stay inside a seeded service")
            parent = alt_state
            for part in parts[:-1]:
                if isinstance(parent, dict) and part in parent:
                    parent = parent[part]
                elif isinstance(parent, list) and part.isdigit() and int(part) < len(parent):
                    parent = parent[int(part)]
                else:
                    raise ValueError(f"{label} replacement path does not exist: {pointer}")
            key = parts[-1]
            if isinstance(parent, list) and key.isdigit() and int(key) < len(parent):
                key = int(key)
            elif not isinstance(parent, dict) or key not in parent:
                raise ValueError(f"{label} replacement leaf does not exist: {pointer}")
            old = parent[key]
            if isinstance(old, (dict, list)) or isinstance(value, (dict, list)) or old == value:
                # Queue 0017: the checker already knows the pointer, the current
                # value's type, and the scalar leaves on the same node.  The
                # Author only ever saw "container/no-op", so it guessed.  Name
                # the exact scalars it can target instead.
                scalar_leaves: list[str] = []
                if isinstance(parent, dict):
                    for sibling_key, sibling_value in parent.items():
                        if isinstance(sibling_value, (dict, list)):
                            continue
                        try:
                            unchanged = sibling_value == value
                        except Exception:  # noqa: BLE001 - exotic values are not comparable
                            unchanged = False
                        if not unchanged:
                            scalar_leaves.append(str(sibling_key))
                reason = (
                    "the replacement equals the current value"
                    if old == value
                    else f"the current value is a {type(old).__name__} "
                    f"and the replacement is a {type(value).__name__}"
                )
                raise ValueError(
                    f"{label} must change an existing scalar, not a container/no-op; "
                    f"pointer {pointer!r}: {reason}; scalar leaves on this node you can "
                    f"target instead: {scalar_leaves[:12]}"
                )
            parent[key] = copy.deepcopy(value)
        state_sha = _sha(alt_state)
        if state_sha in seen_states:
            raise ValueError(f"{label} duplicates another policy world")
        seen_states.add(state_sha)
        replacements = row["assertion_replacements"]
        if not isinstance(replacements, dict) or not replacements:
            raise ValueError(f"{label} must bind the different expected outcome")
        alt_assertions = copy.deepcopy(assertions)
        for raw_index, assertion in replacements.items():
            if not isinstance(raw_index, str) or not raw_index.isdigit() or str(int(raw_index)) != raw_index:
                raise ValueError(f"{label} assertion replacement index must be canonical")
            position = int(raw_index)
            if position >= len(assertions) or not isinstance(assertion, dict):
                raise ValueError(f"{label} assertion replacement index/object invalid")
            if assertion.get("type") != assertions[position].get("type"):
                # Queue 0017: a replacement must stay the same official
                # assertion type.  Echo the expected type and the copyable
                # original row instead of only naming the rule.
                raise ValueError(
                    f"{label} must preserve native assertion types and coverage; "
                    f"assertion_replacements[{raw_index}] has type "
                    f"{assertion.get('type')!r} but assertions[{position}].type is "
                    f"{assertions[position].get('type')!r}; copy assertions[{position}] "
                    f"and change only the expected value fields, keeping these keys: "
                    f"{sorted(assertions[position])}"
                )
            if set(assertion) != set(assertions[position]) or any(
                assertion.get(flag) != assertions[position].get(flag)
                for flag in ("excluded", "scored", "guardrail")
            ):
                missing = sorted(set(assertions[position]) - set(assertion))
                extra = sorted(set(assertion) - set(assertions[position]))
                changed_flags = {
                    flag: {
                        "expected": assertions[position].get(flag),
                        "given": assertion.get(flag),
                    }
                    for flag in ("excluded", "scored", "guardrail")
                    if assertion.get(flag) != assertions[position].get(flag)
                }
                raise ValueError(
                    f"{label} cannot remove assertion fields or change scoring flags; "
                    f"assertion_replacements[{raw_index}] is missing {missing}, adds "
                    f"{extra}, and changed flags {changed_flags}; submit exactly the "
                    f"key set {sorted(assertions[position])} with the original flag "
                    f"values"
                )
            alt_assertions[position] = copy.deepcopy(assertion)
        actions = row["oracle_actions"]
        if not isinstance(actions, list) or len(actions) > 64:
            raise ValueError(f"{label}.oracle_actions must be a bounded action list")
        if cohort:
            alternate=validate_cohort(alt_state,alt_assertions,reference=cohort,actions=actions)
            vector=tuple(alternate['status_vector'])
            if vector in seen_vectors:raise ValueError('coordinated policy outcome vectors must be pairwise distinct')
            seen_vectors.add(vector)

        def execute(seed, expected, path_actions, name):
            world = WorldState(**normalize_runtime_value(copy.deepcopy(seed)))
            world.meta.allowed_services = list(allowed_services)
            reset_campaigns=copy.deepcopy(world.google_ads.campaigns) if cohort else None
            receipts, count = _execute_official_action_sequence(
                official=official, world=world, actions=path_actions, label=f"{label}.{name}")
            if cohort and name=='alternate_correct':
                validate_cohort(seed,expected,world,reference=cohort,actions=path_actions,reset_campaigns=reset_campaigns)
            score = _official_score(initial_state=seed, assertions=expected, world=world)
            checks = score['assertion_results']
            return {"strict_pass": score["strict_pass"], "partial_credit": score["partial_credit"],
                    "scored_assertion_count": sum(not row.get('excluded', False) for row in checks),
                    "failed_assertion_indices": [i for i, row in enumerate(checks)
                        if not row.get('passed') and not row.get('excluded', False)],
                    "action_receipts": receipts, "state_changing_call_count": count,
                    "terminal_state_sha256": _sha(world.model_dump(mode="json"))}

        correct = execute(alt_state, alt_assertions, actions, "alternate_correct")
        stale = execute(alt_state, alt_assertions, oracle_actions, "base_path_in_alternate")
        reverse = execute(initial_state, assertions, actions, "alternate_path_in_base")
        if not correct["strict_pass"] or stale["strict_pass"] or reverse["strict_pass"]:
            diagnostics = {name: {key: case[key] for key in (
                'strict_pass', 'partial_credit', 'scored_assertion_count', 'failed_assertion_indices')}
                for name, case in [('alternate_correct', correct), ('base_path_in_alternate', stale),
                                   ('alternate_path_in_base', reverse)]}
            diagnostics['hint'] = (
                'Indices refer to authored assertions. Zero scored assertions is not full credit: '
                'the official scorer excludes already-true free assertions. For a legitimate hold/no-op '
                'branch, explicitly bind its public outcome with excluded=false in the corresponding '
                'base assertion as well; fixtures preserve flags. Do not add an unrelated effect or '
                'weaken another obligation to obtain credit.'
            )
            raise ValueError(f"{label} requires alternate_correct=true, base_path_in_alternate=false, "
                             f"alternate_path_in_base=false; observed "
                             f"{correct['strict_pass']}/{stale['strict_pass']}/{reverse['strict_pass']}; "
                             + _canonical(diagnostics))
        results.append({"scenario": f"opposite_policy_{index}", "passed": True,
                        **({'native_coordinated_status':alternate} if cohort else {}),
                        **({'native_independent_fact': fact_witnesses[index]} if fact_witnesses else {}),
                        **({'native_dependency_witness': dependency_witnesses[index]} if dependency_witnesses else {}),
                        "resolved_public_policy_basis": basis,
                        "public_basis_reference_contract": native_cases.PUBLIC_BASIS_CONTRACT,
                        "fixture_sha256": _sha(row), "alternate_initial_state_sha256": state_sha,
                        "alternate_assertions_sha256": _sha(alt_assertions),
                        "alternate_correct": correct, "base_path_in_alternate": stale,
                        "alternate_path_in_base": reverse,
                        "same_public_instruction": True, "official_scorer_modified": False})
    return results


def _run_scorer_counterexample_matrix(
    *,
    official: Mapping[str, Any],
    WorldState: Any,
    initial_state: dict[str, Any],
    assertions: list[dict[str, Any]],
    oracle_actions: list[dict[str, Any]],
    oracle_world: Any,
    allowed_services: list[str],
    tests: Any,
    minimum_effect_calls: int = 2,
) -> list[dict[str, Any]]:
    """Run a fixed semantic test matrix against the pinned official scorer.

    The Author chooses every concrete action.  This mechanical gate proves that the
    submitted positive variant and the required multi-probe counterexamples execute,
    touch distinct state surfaces within repeated semantic families, and receive their
    declared official strict outcomes.
    """

    if not isinstance(tests, list):
        raise ValueError("scorer_counterexample_tests must be a list")
    required_test_count = sum(SCORER_COUNTEREXAMPLE_MIN_COUNTS.values())
    if not required_test_count <= len(tests) <= 512:
        raise ValueError(
            "scorer_counterexample_tests must contain the required minimum multi-probe "
            f"matrix of {required_test_count} rows and at most 512 field-closing probes"
        )
    observed_categories: Counter[str] = Counter()
    observed_action_sequences: set[str] = set()
    observed_changed_surfaces: dict[str, set[str]] = defaultdict(set)
    results: list[dict[str, Any]] = []
    oracle_sequence = _canonical(oracle_actions)
    for index, row in enumerate(tests):
        label = f"scorer_counterexample_tests[{index}]"
        if not isinstance(row, Mapping):
            raise ValueError(f"{label} must be an object")
        if set(row) != {"category", "start_state", "actions", "expected_strict"}:
            raise ValueError(
                f"{label} must contain exactly category, start_state, actions, "
                f"expected_strict; this row has {sorted(row)}; "
                f"missing={sorted({'category','start_state','actions','expected_strict'} - set(row))}, "
                f"unexpected={sorted(set(row) - {'category','start_state','actions','expected_strict'})}"
            )
        category = str(row.get("category") or "")
        if category not in SCORER_COUNTEREXAMPLE_EXPECTATIONS:
            raise ValueError(f"{label} has unsupported category: {category}")
        observed_categories[category] += 1
        expected_strict = row.get("expected_strict")
        if not isinstance(expected_strict, bool):
            raise ValueError(f"{label}.expected_strict must be boolean")
        if expected_strict is not SCORER_COUNTEREXAMPLE_EXPECTATIONS[category]:
            raise ValueError(
                f"{label}.expected_strict contradicts category {category}"
            )
        start_state = str(row.get("start_state") or "")
        if start_state not in {"initial", "oracle_complete"}:
            raise ValueError(
                f"{label}.start_state must be initial or oracle_complete"
            )
        required_start_state = SCORER_COUNTEREXAMPLE_START_STATES[category]
        if start_state != required_start_state:
            raise ValueError(
                f"{category} must start from {required_start_state}"
            )
        actions_value = row.get("actions")
        if (
            not isinstance(actions_value, list)
            or not actions_value
            or len(actions_value) > 24
        ):
            raise ValueError(f"{label}.actions must contain 1-24 calls")
        actions = copy.deepcopy(actions_value)
        action_sequence = _canonical(actions)
        if action_sequence in observed_action_sequences:
            raise ValueError("scorer counterexample action sequences must be distinct")
        observed_action_sequences.add(action_sequence)
        if category == "equivalent_valid_path" and action_sequence == oracle_sequence:
            raise ValueError(
                "equivalent_valid_path must differ from the canonical oracle action order or payload"
            )

        if start_state == "oracle_complete":
            test_world = copy.deepcopy(oracle_world)
        else:
            test_world = WorldState(**normalize_runtime_value(copy.deepcopy(initial_state)))
            test_world.meta.allowed_services = list(allowed_services)
        before_dump = test_world.model_dump(mode="json")
        before_sha = _sha(before_dump)
        receipts, mutation_count = _execute_official_action_sequence(
            official=official,
            world=test_world,
            actions=actions,
            label=label,
        )
        after_dump = test_world.model_dump(mode="json")
        after_sha = _sha(after_dump)
        changed_paths = sorted(_changed_leaf_paths(before_dump, after_dump))
        if mutation_count < 1 or before_sha == after_sha:
            raise ValueError(
                f"{label} must execute at least one genuine state mutation"
            )
        if category == "equivalent_valid_path" and mutation_count < minimum_effect_calls:
            raise ValueError(
                "equivalent_valid_path must retain the task's multi-mutation complexity"
            )
        changed_surface_sha = _sha(changed_paths)
        if changed_surface_sha in observed_changed_surfaces[category]:
            raise ValueError(
                f"{category} probes must mutate distinct persisted state surfaces"
            )
        observed_changed_surfaces[category].add(changed_surface_sha)
        score = _official_score(
            initial_state=initial_state,
            assertions=assertions,
            world=test_world,
        )
        if score["strict_pass"] is not expected_strict:
            raise ValueError(
                f"{label} expected strict={expected_strict}, observed "
                f"strict={score['strict_pass']} partial={score['partial_credit']}"
            )
        results.append({
            "category": category,
            "start_state": start_state,
            "expected_strict": expected_strict,
            "observed_strict": score["strict_pass"],
            "partial_credit": score["partial_credit"],
            "state_changing_call_count": mutation_count,
            "changed_path_count": len(changed_paths),
            "changed_surface_sha256": changed_surface_sha,
            "action_sequence_sha256": hashlib.sha256(
                action_sequence.encode("utf-8")
            ).hexdigest(),
            "action_receipts": receipts,
        })
    if any(
        observed_categories[category] < minimum
        for category, minimum in SCORER_COUNTEREXAMPLE_MIN_COUNTS.items()
    ):
        raise ValueError("scorer counterexample category coverage is incomplete")
    return results


def _validate_action_assertion_shape(assertions: list[dict[str, Any]]) -> None:
    """Reject fields that the official generic action assertions silently ignore.

    The pinned official ``*_action_exists``/``*_action_not_exists`` handlers match
    ``action_key`` and the nested ``params`` object.  Entity identifiers placed at
    the assertion top level (for example ``id``) are not consulted, which otherwise
    creates a convincing but ineffective target guard.
    """

    allowed_keys = {"type", "action_key", "params", "excluded"}
    for index, assertion in enumerate(assertions):
        assertion_type = str(assertion.get("type") or "")
        if not re.fullmatch(r"[a-z0-9_]+_action_(?:not_)?exists", assertion_type):
            continue
        ignored_keys = sorted(set(assertion) - allowed_keys)
        if ignored_keys:
            raise ValueError(
                f"assertions[{index}] {assertion_type} contains top-level fields ignored "
                f"by the official action matcher: {ignored_keys}; put every target "
                "identifier and matched business field inside params"
            )
        if not isinstance(assertion.get("params", {}), dict):
            raise ValueError(
                f"assertions[{index}] {assertion_type}.params must be an object"
            )


def _seeded_scalar_strings(value: Any) -> set[str]:
    output: set[str] = set()
    if isinstance(value, str) and value.strip():
        output.add(value.strip())
    elif isinstance(value, Mapping):
        for child in value.values():
            output.update(_seeded_scalar_strings(child))
    elif isinstance(value, list):
        for child in value:
            output.update(_seeded_scalar_strings(child))
    return output


def _validate_public_observability_contract(
    instruction: str,
    assertions: list[dict[str, Any]],
) -> None:
    """Reject irreversible-history promises absent from the official scorer surface.

    Natural sequencing and source-review wording are common in the pinned official public
    tasks, whose scorer intentionally evaluates the resulting state.  Those shapes remain
    auditable advisories for the independent Reviewer, but are not native incompatibilities.
    """

    lowered = instruction.lower()
    assertion_types = [str(row.get("type") or "").lower() for row in assertions]
    # In the pinned public set, an ordinary imperative such as "do not create
    # another ticket" denotes the required final state and is routinely scored
    # with a not-exists assertion.  Treat it as an audit signal below.  Only
    # explicit *historical* language promises that even a create-then-delete
    # execution never happened, which the final-state scorer cannot observe.
    mutation = r"(?:create|apply|add|remove|send|post|update|delete|archive)"
    historical_ban = bool(
        re.search(rf"\bnever\s+{mutation}\b", lowered)
        or re.search(rf"\b(?:do not|don't)\s+ever\s+{mutation}\b", lowered)
        or re.search(
            rf"\b(?:at any (?:time|point)|even temporarily)\b[^.!?\n]{{0,80}}"
            rf"\b{mutation}\b",
            lowered,
        )
        or re.search(
            rf"\bwithout\s+ever\s+(?:creating|applying|adding|removing|sending|"
            r"posting|updating|deleting|archiving)\b",
            lowered,
        )
    )
    if historical_ban:
        has_creation_history_guard = any(
            "action_not_exists" in assertion_type or "history" in assertion_type
            for assertion_type in assertion_types
        )
        if not has_creation_history_guard:
            raise ValueError(
                "public task forbids creation historically, but final-state not-exists assertions "
                "cannot reject create-then-delete; add an official action/history guard or narrow "
                "the promise to the final state"
            )
    # Keep the two official-distribution-compatible patterns visible to callers via
    # `_public_observability_advisories`; only an irreversible history prohibition is
    # a hard native/scorer mismatch here.


def _public_observability_advisories(
    instruction: str,
    assertions: list[dict[str, Any]],
) -> list[str]:
    """Return non-blocking process-language signals for the independent Reviewer."""

    lowered = instruction.lower()
    assertion_types = [str(row.get("type") or "").lower() for row in assertions]
    has_sequence_observer = any(
        any(token in assertion_type for token in ("history", "sequence", "order", "timeline"))
        for assertion_type in assertion_types
    )
    signals: list[str] = []
    action_pattern = r"(?:create|update|set|post|send|add|delete|archive|close|open|move|assign|comment|react|finish|record)"
    # In a qualified field label, "record" is a noun. Mask only that token,
    # keeping offsets and all surrounding verbs: "then update the Registry
    # Record title" must still signal a requested execution order.
    sequence_text = re.sub(
        r"\b(?:registry|routing|customer|employee|source|target|protected)\s+"
        r"(?P<noun>record)(?=\s+(?:title|id|identifier|name)\b)",
        lambda match: match.group().replace("record", " " * len("record")),
        lowered,
    )
    sequence_pattern = re.compile(
        r"\b(?:then|after(?:ward|wards)?|before|finally|last(?:ly)?)\b"
        rf"(?=[^.!?\n]{{0,96}}\b{action_pattern}\b)|"
        r"\bfinish\s+with\b",
    )
    if not has_sequence_observer:
        for match in sequence_pattern.finditer(sequence_text):
            if match.group() == 'finish with' and re.match(
                r'\s+(?:exactly\s+)?(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+'
                r'(?:tickets?|events?|envelopes?|rows?|files?|records?|cards?)\s*(?:[.!?;]|$)',
                lowered[match.end():]
            ):
                # A bounded final collection cardinality is observable state.
                # Do not extend this to "finish with three updates" or verbs.
                continue
            if match.group() == 'finish with' and re.match(
                r'\s+(?:the\s+)?(?:ticket|event|envelope|row|file|record)\s+'
                r'(?:status|priority|location|name|title|value)\b', lowered[match.end():]
            ):
                # A named terminal field/value is not an action to execute last.
                # "finish with sending/updating ..." remains a process signal.
                continue
            if match.group() in {'before', 'after'} and re.match(
                r'\s+\d{4}-\d{2}-\d{2}\b', lowered[match.end():]
            ):
                # A literal date operand inside an explicit if condition is
                # not a model-execution schedule or a tool-order obligation.
                # Do not generalize this exception to actions or unknown prose.
                prefix = re.split(r'[.!?\n]', lowered[:match.start()])[-1]
                conditions = list(re.finditer(r'\bif\b', prefix))
                if conditions and not re.search(
                    rf'\b{action_pattern}\b', prefix[conditions[-1].end():]
                ):
                    continue
            if match.group() == "then":
                presentation_prefix = re.split(r'[.!?\n]', lowered[:match.start()])[-1]
                if (re.search(r'\bdescription\s+exactly\s+two\s+lines:\s*'
                              r'[^\n]*\bline\s+first,\s*$', presentation_prefix)
                        and re.match(r'\s+add\s+[`"“][^`"”\n]+[`"”]',
                                     lowered[match.end():])):
                    # The explicit two-line result specifies text order, not API order.
                    continue
                # "If eligible, then set priority" is a state/policy branch,
                # not a promise about invisible tool order. Keep a later
                # "then" after a real action detectable in the same sentence.
                prefix = re.split(r"[.!?\n]", lowered[:match.start()])[-1]
                conditions = list(re.finditer(r"\bif\b", prefix))
                if conditions:
                    condition = prefix[conditions[-1].end():]
                    if not re.search(rf"\b{action_pattern}\b", condition):
                        continue
            signals.append("unscored_natural_action_sequence")
            break
    process_sentence = re.search(
        r"(?:^|[.!?]\s+)(?:review|read|inspect|check|examine|audit)\b"
        r"[^.!?\n]{0,120}\b(?:full|entire|all|every|history|histories|record|records)\b",
        lowered,
    )
    if process_sentence and not has_sequence_observer:
        signals.append("unscored_source_review_coverage")
    if (
        re.search(
            r"\b(?:do not|don't)\s+(?:create|apply|add|remove|send|post|update|"
            r"delete|archive)\b|\bwithout\s+(?:creating|applying|adding|removing|"
            r"sending|posting|updating|deleting|archiving)\b",
            lowered,
        )
        and not any(
            "action_not_exists" in assertion_type or "history" in assertion_type
            for assertion_type in assertion_types
        )
    ):
        signals.append("final_state_only_mutation_prohibition")
    return signals




def _oracle_action_target_service(action: Mapping[str, Any]) -> str:
    """Use the very same service router as execution, never URL-substring guesses.

    A worksheet named 'Jira Intake' is still a Google Sheets write; conversely,
    Google's normal hostnames do not contain the internal 'google_sheets' key.
    """
    official = _official_imports()
    _, router = official["url_to_internal_path"](str(action.get("url") or ""))
    if router is None:
        raise ValueError("oracle action URL has no supported official service route")
    service = str(official["router_service"](router))
    if not service:
        raise ValueError("oracle action service cannot be identified by the official router")
    return service


@immutable_proof
def _validate_known_native_enum_values(
    initial_state: dict[str, Any],
    assertions: list[dict[str, Any]],
) -> None:
    """Fail closed on pinned native enums whose values are externally fixed."""

    scheduled_events = (
        ((initial_state.get("calendly") or {}).get("scheduled_events") or [])
        if isinstance(initial_state.get("calendly"), Mapping)
        else []
    )
    # Official the pinned runtime uses all four spellings: the pinned corpus writes both
    # `canceled` and `cancelled` (sales.calendly_meeting_prep,
    # sales.calendly_no_show_followup) and `completed`
    # (sales.calendly_no_show_reengagement).  The whitelist previously held only
    # `active`/`canceled`, so this gate rejected 2 of the 600 official tasks --
    # i.e. it was stricter than the official schema it claims to enforce
    # (supervisor 2026-09-15 §101 calibration: 598/600).
    allowed_calendly_statuses = {"active", "canceled", "cancelled", "completed"}
    for index, row in enumerate(scheduled_events):
        if not isinstance(row, Mapping) or row.get("status") in (None, ""):
            continue
        status = str(row.get("status")).casefold()
        if status not in allowed_calendly_statuses:
            raise ValueError(
                f"initial_state.calendly.scheduled_events[{index}].status uses "
                f"non-native Calendly enum {row.get('status')!r}; allowed values are "
                "active, canceled, cancelled and completed"
            )
    for index, assertion in enumerate(assertions):
        assertion_type = str(assertion.get("type") or "")
        field = str(assertion.get("field") or "").casefold()
        if not assertion_type.startswith("calendly_event_") or field != "status":
            continue
        value = assertion.get("value")
        if value not in (None, "") and str(value).casefold() not in allowed_calendly_statuses:
            raise ValueError(
                f"assertions[{index}] uses non-native Calendly status {value!r}"
            )


def _validate_append_serialization_contract(
    instruction: str,
    assertions: list[dict[str, Any]],
    initial_state: dict[str, Any],
) -> None:
    """Reject a secret newline/whitespace convention hidden behind exact equality."""

    lowered = instruction.lower()
    if not re.search(r"\b(?:append|add)\b", lowered):
        return
    # An unrelated "add an attendee" never turns every assertion identifier/value
    # into appended text. Require the named destination in that text-edit clause.
    text_fields = {'description', 'body', 'text', 'topic', 'summary', 'title',
                   'note', 'comment', 'message', 'subject'}
    appended_fields: set[str] = set()
    for clause in re.split(r'[;\n]|(?<=[.!?])\s+(?=[A-Z])', instruction):
        clause = clause.casefold()
        if re.search(r'\bappend\b', clause) or re.search(
            r'\badd\b[^;\n]{0,160}\b(?:to|onto)\b', clause
        ):
            appended_fields.update(field for field in text_fields
                                   if re.search(rf'\b{field}\b', clause))
    if not appended_fields:
        return
    delimiter_is_public = bool(
        re.search(
            r"\b(?:new\s*line|newline|separate\s+line|blank\s+line|paragraph|"
            r"exact\s+(?:final\s+)?(?:text|value|description|body|note))\b",
            lowered,
        )
    )
    if delimiter_is_public:
        return
    seeded = _seeded_scalar_strings(initial_state)
    for index, assertion in enumerate(assertions):
        for key, value in assertion.items():
            if key.endswith("_contains") or not isinstance(value, str):
                continue
            field = str(assertion.get('field') or '').casefold() if key == 'value' else key
            if field not in appended_fields:
                # type, column, object IDs and unrelated preserved fields are not
                # text being appended. Unknown semantic mappings need independent
                # review; global prefix overlap is not a proof of a hard defect.
                continue
            for original in seeded:
                if value.startswith(original) and len(value) > len(original):
                    separator = value[len(original):]
                    if separator.startswith(("\n", "\r", " ", "\t")):
                        raise ValueError(
                            f"assertions[{index}].{key} silently fixes the whitespace delimiter "
                            "for an append request; disclose the canonical delimiter publicly "
                            "or use a scorer that accepts harmless serialization variants"
                        )


def _services_with_collection_growth(before: Any, after: Any) -> set[str]:
    """Return top-level official services containing any newly appended collection row."""

    def dump(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return value

    before_value = dump(before)
    after_value = dump(after)
    grew: set[str] = set()

    def collection_grew(left: Any, right: Any) -> bool:
        if isinstance(left, list) and isinstance(right, list):
            if len(right) > len(left):
                return True
            return any(
                collection_grew(a, b) for a, b in zip(left, right, strict=False)
            )
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            return any(
                collection_grew(left.get(key), right.get(key))
                for key in set(left) | set(right)
            )
        return False

    if isinstance(before_value, Mapping) and isinstance(after_value, Mapping):
        for service, right in after_value.items():
            if service == "meta":
                continue
            if collection_grew(before_value.get(service), right):
                grew.add(str(service))
    return grew


class OfficialTaskPackageTool:
    """Compile and test one agent-authored task on the official implementation."""

    name = "compile_and_test_task_package"
    description = (
        "Submit one complete task that you authored for the pinned official Runtime "
        "runtime/scorer. candidate_markdown is natural-language Markdown. task_source contains "
        "exactly task_instruction, initial_state, assertions, oracle_actions, "
        "forbidden_extra_actions, optional scorer_counterexample_tests, optional "
        "scorer_obligation_ledger with field-granular state_paths, optional "
        "state_surface_manifest, optional contract_closure_manifest, and optional "
        "tool_names. Use inspect_official_task_contract "
        "before authoring each app/assertion. "
        "initial_state must validate as official WorldState; assertions must be existing registered "
        "official types; oracle_actions are private api_fetch calls proving a full-credit path. "
        "Each forbidden_extra_action is a valid state-changing api_fetch call appended separately "
        "to the oracle state; the official scorer must reject every such over-completion. "
        "When counterexamples are required, state_surface_manifest must classify every seeded "
        "JSON leaf exactly once. Protected rows use exact leaf paths; one bounded out_of_scope "
        "row may cover a whole seeded subtree. Each row has state_path, classification "
        "(required_effect_target, decision_source, protected_non_target, or out_of_scope), "
        "public_basis, assertion_indices, and counterexample_test_indices. Protected rows bind "
        "exactly one official assertion and one exclusive persisted counterexample; out_of_scope "
        "rows explain the bounded exclusion and bind neither. When contract closure is required, "
        "contract_closure_manifest additionally binds every in-scope collection, all selection "
        "collections, oracle-grown collections with exact count and stable identity assertions, "
        "cross-record dependency edges, and final-state versus event-history semantics. The fixed "
        "counterexample category matrix is a minimum; add exclusive field-closing probes as needed. "
        "The first submission contains candidate_markdown and task_source. After a rejected "
        "submission, prefer repair_fields plus the exact base_revision_sha256 returned by the tool; "
        "each entry replaces one complete top-level Author field while every unmentioned field remains "
        "stable and the tool revalidates the complete package. The tool does not invent task content "
        "and never exposes oracle actions to the executor."
    )
    parameters = {
        "type": "object",
        "properties": {
            "candidate_markdown": {"type": "string"},
            "task_source": {
                "type": "object",
                "description": (
                    "Private official task source: task_instruction, initial_state, assertions, "
                    "oracle_actions, forbidden_extra_actions, optional "
                    "scorer_counterexample_tests, optional scorer_obligation_ledger and "
                    "state_surface_manifest, optional contract_closure_manifest, and tool_names. Each action "
                    "has method, url, and optional params/body (objects or JSON strings)."
                ),
                "additionalProperties": True,
            },
            "semantic_graph": {
                "type": "object",
                "description": (
                    "Author-owned semantic truth with stable assertion, counterexample and "
                    "requirement IDs. Each requirement owns its state bindings; the compiler "
                    "deterministically derives redundant official task_source indices, state "
                    "classifications and manifests without inventing business semantics."
                ),
                "properties": {
                    "schema_version": {"type": "string"},
                    "task_instruction": {"type": "string"},
                    "initial_state": {"type": "object", "additionalProperties": True},
                    "oracle_actions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "method": {"type": "string"},
                                "url": {"type": "string"},
                                "params": {},
                                "body": {},
                            },
                            "required": ["method", "url"],
                            "additionalProperties": False,
                        },
                    },
                    "forbidden_extra_actions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "method": {"type": "string"},
                                "url": {"type": "string"},
                                "params": {},
                                "body": {},
                            },
                            "required": ["method", "url"],
                            "additionalProperties": False,
                        },
                    },
                    "tool_names": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "assertion_nodes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "assertion": {"type": "object", "additionalProperties": True},
                            },
                            "required": ["id", "assertion"],
                            "additionalProperties": False,
                        },
                    },
                    "counterexample_nodes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "counterexample": {
                                    "type": "object",
                                    "additionalProperties": True,
                                },
                            },
                            "required": ["id", "counterexample"],
                            "additionalProperties": False,
                        },
                    },
                    "requirement_nodes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "obligation_kind": {"type": "string"},
                                "requirement": {"type": "string"},
                                "state_bindings": {
                                    "type": "object",
                                    "additionalProperties": {},
                                },
                                "assertion_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "counterexample_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": [
                                "id",
                                "obligation_kind",
                                "requirement",
                                "state_bindings",
                                "assertion_ids",
                                "counterexample_ids",
                            ],
                            "additionalProperties": False,
                        },
                    },
                    "out_of_scope_state": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                    "closure": {
                        "type": "object",
                        "properties": {
                            "creation_collections": {
                                "type": "array",
                                "items": {"type": "object"},
                            },
                            "temporality": {"type": "object"},
                        },
                        "additionalProperties": True,
                    },
                },
                "required": [
                    "schema_version",
                    "task_instruction",
                    "initial_state",
                    "oracle_actions",
                    "forbidden_extra_actions",
                    "tool_names",
                    "assertion_nodes",
                    "counterexample_nodes",
                    "requirement_nodes",
                    "out_of_scope_state",
                    "closure",
                ],
                "additionalProperties": False,
            },
            "repair_patch": {
                "type": "array",
                "description": (
                    "On a repair call, 1-128 RFC-6902 add/replace/remove operations rooted under "
                    "/candidate_markdown or /task_source. Unmentioned draft content remains byte-stable."
                ),
                "items": {"type": "object"},
            },
            "repair_fields": {
                "type": "object",
                "description": (
                    "Preferred semantic repair: replace 1-16 complete top-level Author fields, "
                    "keyed by candidate_markdown or semantic_graph.<field>. Unmentioned fields "
                    "remain byte-stable and all native gates rerun. Do not use nested paths."
                ),
                "additionalProperties": True,
            },
            "base_revision_sha256": {
                "type": "string",
                "description": "Exact draft_revision_sha256 returned by the preceding compile result.",
            },
        },
        "required": [],
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        candidate_relative_path: str,
        candidate_id: str,
        domain: str,
        rubric_sha256: str,
        rubric_text: str | None = None,
        require_scorer_counterexamples: bool = False,
        require_contract_closure: bool = False,
        require_semantic_graph: bool = False,
        compact_official_task_source: bool = False,
        minimal_author_tools: bool = False,
        require_selection_contract: bool = False,
        turn_index_getter: Callable[[], int] | None = None,
        profile_flags: Mapping[str, Any] | None = None,
    ) -> None:
        self._candidate_relative_path = candidate_relative_path
        self._candidate_id = candidate_id
        self._domain = domain
        self._rubric_sha256 = rubric_sha256
        if rubric_text is not None and hashlib.sha256(rubric_text.encode("utf-8")).hexdigest() != rubric_sha256:
            raise ValueError("rubric_text does not match rubric_sha256")
        self._rubric_mechanical_profile = (
            _rubric_mechanical_profile(rubric_text) if rubric_text is not None else {}
        )
        # User directive 2026-09-15: the Rubric is prose for the Author, never a
        # configuration file.  Every flag the pipeline needs is supplied
        # explicitly here (frozen machine config) and applied on top of whatever
        # a legacy Rubric happened to spell out, so rewording the Rubric can
        # never silently switch a gate off again.
        if profile_flags:
            self._rubric_mechanical_profile.update(dict(profile_flags))
        _validate_private_evidence_gate(self._rubric_mechanical_profile)
        self._require_scorer_counterexamples = require_scorer_counterexamples
        self._require_contract_closure = require_contract_closure
        self._require_semantic_graph = require_semantic_graph
        self._compact_official_task_source = compact_official_task_source
        # Kept as an explicit immutable flag for the Author harness; tool
        # registration is applied by the outer runner, while the package
        # accepts the binding so plan/profile hashes remain stable.
        self._minimal_author_tools = bool(minimal_author_tools)
        self._require_selection_contract = require_selection_contract or bool(
            self._rubric_mechanical_profile.get('strict_minimum_native_join_pairs'))
        if self._require_selection_contract and not self._compact_official_task_source:
            raise ValueError("selection contract requires compact official task source")
        if self._rubric_mechanical_profile.get("strict_opposite_policy_fixture") and not self._compact_official_task_source:
            raise ValueError("opposite-policy fixture requires its supported compact Author interface")
        if self._compact_official_task_source and (
            self._require_semantic_graph
            or self._require_scorer_counterexamples
            or self._require_contract_closure
        ):
            raise ValueError(
                "compact official task source is mutually exclusive with semantic-graph, "
                "counterexample-matrix and contract-closure author surfaces"
            )
        # A semantic lineage must expose exactly one submission/repair protocol to the
        # provider.  Leaving the legacy task_source and RFC-6902 repair_patch branches in
        # the advertised tool schema caused agents to mix two incompatible contracts even
        # though the runtime eventually rejected them.  Keep the legacy class-level schema
        # intact for historical lineages, but narrow each semantic instance fail-closed.
        self.parameters = copy.deepcopy(type(self).parameters)
        if self._require_semantic_graph:
            properties = self.parameters["properties"]
            properties.pop("task_source", None)
            properties.pop("repair_patch", None)
            self.description = (
                "Submit one complete Author-owned semantic graph for the pinned official "
                "Runtime runtime/scorer. The first call contains only candidate_markdown "
                "and semantic_graph. After rejection, repair only with base_revision_sha256 and "
                "repair_fields; every key must be candidate_markdown or one complete "
                "semantic_graph.<top-level-field>. Legacy task_source, RFC-6902 repair_patch, "
                "nested repair paths, fictional apps/endpoints/assertions and custom scorers are "
                "forbidden. Every official native gate is rerun after each repair."
            )
        elif self._compact_official_task_source:
            properties = self.parameters["properties"]
            properties.pop("semantic_graph", None)
            properties.pop("repair_patch", None)
            properties["repair_fields"]["description"] = (
                "Replace 1-16 complete top-level Author fields, keyed by candidate_markdown "
                "or task_source.<field>. Use the exact base_revision_sha256 returned by the "
                "preceding compile result. Unmentioned fields remain byte-stable and all "
                "native gates rerun. Put application state inside task_source.initial_state; "
                "do not use nested paths or put replacement fields beside repair_fields."
            )
            properties["task_source"] = {
                "type": "object",
                "description": (
                    "The compact private implementation paired with candidate_markdown. "
                    "Supply exactly the official WorldState, official assertions, oracle "
                    "actions, forbidden over-completion actions and executor tools. The public "
                    "task instruction is derived deterministically from candidate_markdown and "
                    "must not be duplicated here."
                ),
                "properties": {
                    "initial_state": {"type": "object", "additionalProperties": True},
                    "assertions": {
                        "type": "array",
                        "items": {"type": "object", "additionalProperties": True},
                    },
                    "oracle_actions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "method": {"type": "string"},
                                "url": {"type": "string"},
                                "params": {},
                                "body": {},
                            },
                            "required": ["method", "url"],
                            "additionalProperties": False,
                        },
                    },
                    "forbidden_extra_actions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "method": {"type": "string"},
                                "url": {"type": "string"},
                                "params": {},
                                "body": {},
                            },
                            "required": ["method", "url"],
                            "additionalProperties": False,
                        },
                    },
                    "selection_contract": {
                        "type": "object",
                        "properties": {
                            "predicates": {"type": "array", "items": {"type": "object"}},
                            "candidates": {"type": "array", "items": {"type": "object"}},
                            "selected_candidate_id": {"type": "string"},
                        },
                        "required": [
                            "predicates",
                            "candidates",
                            "selected_candidate_id",
                        ],
                        "additionalProperties": False,
                    },
                    "native_construction_cases": native_cases.schema(
                        self._rubric_mechanical_profile.get('required_native_construction_case_categories', ()),
                        require_worksheet_parent=bool(self._rubric_mechanical_profile.get(
                            'strict_google_sheets_scored_row_parent_identity'))),
                    "policy_fixtures": {
                        "type": "array", "minItems": self._rubric_mechanical_profile.get("strict_minimum_policy_fixtures", 1),
                        "maxItems": self._rubric_mechanical_profile.get("strict_maximum_policy_fixtures", 4),
                        "description": (
                            "Private independent opposite-policy construction tests. Keep the same "
                            "public request and base world; specify only existing scalar state changes "
                            "by JSON pointer, replacement assertions by zero-based index (same types), "
                            "and the different correct native action sequence. The compiler resets each "
                            "case, requires its correct path to strict-pass, and cross-tests both paths "
                            "against the opposite world's scorer. Do not write a second full world. "
                            "Unchanged assertions/fields are inherited exactly. These fixtures are not "
                            "additional solver context, tasks, or hidden read/order requirements."
                            " " + POLICY_FIXTURE_SCORING_GUIDANCE
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "public_policy_basis": native_cases.public_basis_schema("Exact quote of the conditional rule in the public request."),
                                "initial_state_replacements": {"type": "object", "additionalProperties": True},
                                "assertion_replacements": {"type": "object", "additionalProperties": {"type": "object"}},
                                "oracle_actions": {"type": "array", "maxItems": 64, "items": {"type": "object"}},
                            },
                            "required": ["public_policy_basis", "initial_state_replacements", "assertion_replacements", "oracle_actions"],
                            "additionalProperties": False,
                        },
                    },
                    "tool_names": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "initial_state",
                    "assertions",
                    "oracle_actions",
                    "forbidden_extra_actions",
                    *(["selection_contract"] if self._require_selection_contract else []),
                    *(["policy_fixtures"] if self._rubric_mechanical_profile.get("strict_opposite_policy_fixture") else []),
                    *(["native_construction_cases"] if self._rubric_mechanical_profile.get(
                        'required_native_construction_case_categories') else []),
                    "tool_names",
                ],
                "additionalProperties": False,
            }
            self.description = (
                "Submit one compact task for the pinned official Runtime runtime. "
                "The first call contains only candidate_markdown and task_source; task_source "
                "contains initial_state, assertions, oracle_actions, forbidden_extra_actions, "
                + (
                    "a code-evaluated selection_contract, and "
                    if self._require_selection_contract
                    else ""
                )
                + "tool_names, policy_fixtures when the Rubric requires an opposite-policy fixture, "
                "and native_construction_cases for its explicit executable-case obligations. task_instruction is derived from "
                "candidate_markdown. After rejection use only the exact "
                "base_revision_sha256 and complete top-level repair_fields. The tool reruns "
                "official WorldState, assertion, public-contract, no-action, oracle, forbidden-"
                "action and runner compatibility gates and never invents task semantics."
            )
        source_schema = self.parameters['properties'].get('task_source', {})
        if self._rubric_mechanical_profile.get('strict_sales_fiveapp_policy_conditions'):
            from .sales_five_app_profile import GUIDANCE
            source_schema['description'] += ' ' + GUIDANCE
            source_schema['properties']['policy_fixtures']['items']['properties']['initial_state_replacements'].update(
                minProperties=1, maxProperties=1)
        if self._rubric_mechanical_profile.get('strict_marketing_fiveapp_policy_conditions'):
            from .marketing_five_app_profile import GUIDANCE
            source_schema['description'] += ' ' + GUIDANCE
            source_schema['properties']['policy_fixtures']['items']['properties']['initial_state_replacements'].update(
                minProperties=1, maxProperties=1)
        if self._rubric_mechanical_profile.get('strict_hr_fiveapp_policy_conditions'):
            from .hr_five_app_profile import GUIDANCE
            source_schema['description'] += ' ' + GUIDANCE
            source_schema['properties']['policy_fixtures']['items']['properties']['initial_state_replacements'].update(
                minProperties=1, maxProperties=1)
        if self._rubric_mechanical_profile.get('strict_native_join_bridges'):
            from .native_join_bridges import GUIDANCE
            source_schema['description'] += ' ' + GUIDANCE
        if self._rubric_mechanical_profile.get('strict_fiveapp_output_source_selection'):
            from .five_app_outcome_sources import GUIDANCE
            source_schema['description'] += ' ' + GUIDANCE
        if self._rubric_mechanical_profile.get('strict_marketing_coordinated_status'):
            from .marketing_coordinated_status import GUIDANCE
            source_schema['description'] += ' ' + GUIDANCE
        if self._rubric_mechanical_profile.get('strict_marketing_status_lifecycle'):
            from .marketing_status_lifecycle import GUIDANCE
            source_schema['description'] += ' ' + GUIDANCE
        if self._rubric_mechanical_profile.get('strict_independent_readable_policy_facts'):
            from .single_app_policy_facts import GUIDANCE
            fixtures_schema = source_schema['properties']['policy_fixtures']
            fixtures_schema['description'] += ' ' + GUIDANCE
            fixtures_schema['items']['properties']['initial_state_replacements'].update(
                minProperties=1, maxProperties=1)
            if self._rubric_mechanical_profile.get('strict_native_fact_json_projection'):
                from .single_app_policy_facts import PROJECTION_GUIDANCE
                fixtures_schema['description'] += ' ' + PROJECTION_GUIDANCE
        if self._rubric_mechanical_profile.get('strict_five_app_native_dependencies'):
            from .multi_app_policy_dependencies import GUIDANCE, join_schema
            fixtures_schema = source_schema['properties']['policy_fixtures']
            fixtures_schema['description'] += ' ' + GUIDANCE
            fixtures_schema['items']['properties']['join_witness'] = join_schema()
            fixtures_schema['items']['required'].append('join_witness')
            if self._rubric_mechanical_profile.get('strict_single_scalar_dependency_intervention'):
                fixtures_schema['items']['properties']['initial_state_replacements'].update(minProperties=1,maxProperties=1)
        if self._rubric_mechanical_profile.get('minimum_cross_application_joins'):
            from .multi_app_policy_dependencies import join_schema
            fixture_schema=source_schema['properties']['policy_fixtures']
            fixture_schema['items']['properties']['join_witness']=join_schema()
            fixture_schema['items']['required'].append('join_witness')
            fixture_schema['description']+=' For two distinct application pairs, change one relationship scalar in a separately reset world. Bind the old and alternate native target identity or unique business-key leaves in join_witness and a fresh same-type target_read_probe_value. Show both keys through nonmutating native reads. Other policy fixtures set join_witness to null. Preserve the public policy and cross-test both outcomes.'
        extra_schema = source_schema.get('properties', {}).get('forbidden_extra_actions')
        if extra_schema is not None:
            extra_schema['description'] = (
                'Independent negative mutations appended to a correct state. Corrupting a required '
                'field or a publicly protected value is valid; creation/delivery is not required. '
                'Do not add unrelated exact-name bans or historical prohibitions merely for this test.'
            )
        self._turn_index_getter = turn_index_getter
        self._last_compile_turn: int | None = None
        self.call_count = 0
        self.accepted_call_count = 0
        self.full_submission_count = 0
        self.repair_patch_count = 0
        self.repair_fields_count = 0
        self.provider_flattened_semantic_field_count = 0
        self.deterministic_semantic_projection_normalization_count = 0
        self.deterministic_semantic_projection_normalization_by_kind = {
            "world_state_service_fold": 0,
            "scored_out_of_scope_dedup": 0,
            "ledger_empty_binding_object": 0,
        }
        self.base_revision_single_nibble_correction_count = 0
        self.compact_source_provider_normalization_count = 0
        self.compact_source_provider_normalization_by_kind = {
            "bare_repair_field_fold": 0,
            "top_level_source_field_fold": 0,
            "source_service_into_initial_state": 0,
            "initial_state_source_field_unfold": 0,
        }
        self.compact_source_task_instruction_derivation_count = 0
        self.compact_source_redundant_task_instruction_drop_count = 0
        self.compact_source_action_ledger_fold_count = 0
        self.compact_source_single_app_local_state_wrap_count = 0
        self.compact_source_presentation_order_normalization_count = 0
        self.compact_source_presentation_order_normalized_paths: list[str] = []
        self.latest_candidate_markdown: str | None = None
        self.latest_runtime_source: dict[str, Any] | None = None
        self.latest_task: dict[str, Any] | None = None
        self.latest_result: dict[str, Any] | None = None
        self.latest_regression: dict[str, Any] | None = None
        self._draft_candidate_markdown: str | None = None
        self._draft_task_source: dict[str, Any] | None = None
        self._draft_revision_sha256: str | None = None
        self.validate_advertised_author_protocol()

    @property
    def _source_root(self) -> str:
        return "semantic_graph" if self._require_semantic_graph else "task_source"

    def validate_advertised_author_protocol(self) -> dict[str, Any]:
        """Check the actual provider-visible repair contract, without a provider call."""
        properties = self.parameters["properties"]
        description = properties["repair_fields"]["description"]
        if self._compact_official_task_source:
            if (
                "task_source.<field>" not in description
                or "semantic_graph" in description
                or "semantic_graph" in properties
                or "repair_patch" in properties
                or "task_source" not in properties
            ):
                raise ValueError("compact Author tool schema contradicts task_source repair protocol")
            source_schema = properties["task_source"]
            categories = self._rubric_mechanical_profile.get('required_native_construction_case_categories', [])
            if categories and ('native_construction_cases' not in source_schema['properties'] or
                               'native_construction_cases' not in source_schema['required'] or
                               source_schema['properties']['native_construction_cases']['minItems'] != len(categories)):
                raise ValueError('Rubric requires native construction cases but tool schema does not bind coverage')
            if self._rubric_mechanical_profile.get("strict_opposite_policy_fixture") and (
                "policy_fixtures" not in source_schema["properties"]
                or "policy_fixtures" not in source_schema["required"]
            ):
                raise ValueError("Rubric requires opposite-policy fixture but tool schema does not")
            if source_schema["properties"]["policy_fixtures"]["minItems"] != self._rubric_mechanical_profile.get("strict_minimum_policy_fixtures", 1):
                raise ValueError("policy fixture count differs from executed profile")
            if source_schema['properties']['policy_fixtures']['maxItems'] != self._rubric_mechanical_profile.get('strict_maximum_policy_fixtures', 4):
                raise ValueError('policy fixture maximum differs from executed profile')
            if self._rubric_mechanical_profile.get('strict_five_app_native_dependencies'):
                from .multi_app_policy_dependencies import GUIDANCE, join_schema
                fixture_schema = source_schema['properties']['policy_fixtures']
                if (fixture_schema['minItems'] != 5 or fixture_schema['maxItems'] != 12
                        or GUIDANCE not in fixture_schema['description']
                        or fixture_schema['items']['properties'].get('join_witness') != join_schema()
                        or 'join_witness' not in fixture_schema['items']['required']):
                    raise ValueError('five-app native dependency gate is not bound in actual Author schema')
                if self._rubric_mechanical_profile.get('strict_single_scalar_dependency_intervention'):
                    replacement=fixture_schema['items']['properties']['initial_state_replacements']
                    if replacement.get('minProperties')!=1 or replacement.get('maxProperties')!=1:
                        raise ValueError('single scalar dependency obligation is not bound in actual Author schema')
            if self._rubric_mechanical_profile.get('minimum_cross_application_joins'):
                from .multi_app_policy_dependencies import join_schema
                fixture_schema=source_schema['properties']['policy_fixtures']
                if (fixture_schema['items']['properties'].get('join_witness') != join_schema()
                        or 'join_witness' not in fixture_schema['items']['required']
                        or fixture_schema['minItems'] < 3
                        or not self._rubric_mechanical_profile.get('strict_named_gate_causal_services')
                        or not self._rubric_mechanical_profile.get('strict_native_evidence_readability')):
                    raise ValueError('role-aware join and policy gates are absent from actual Author contract')
            if self._rubric_mechanical_profile.get('strict_independent_readable_policy_facts'):
                from .single_app_policy_facts import GUIDANCE
                fixture_schema = source_schema['properties']['policy_fixtures']
                replacement_schema = fixture_schema['items']['properties']['initial_state_replacements']
                if (fixture_schema['minItems'] < 3 or GUIDANCE not in fixture_schema['description']
                        or replacement_schema.get('minProperties') != 1
                        or replacement_schema.get('maxProperties') != 1):
                    raise ValueError('independent native fact gate is not bound in actual Author schema')
                if self._rubric_mechanical_profile.get('strict_native_fact_json_projection'):
                    from .single_app_policy_facts import PROJECTION_GUIDANCE
                    if PROJECTION_GUIDANCE not in fixture_schema['description']:
                        raise ValueError('native fact JSON projection is not bound in actual Author schema')
            for case_key, basis_key in [('native_construction_cases', 'public_basis'),
                                        ('policy_fixtures', 'public_policy_basis')]:
                basis_schema = source_schema['properties'][case_key]['items']['properties'][basis_key]
                variants = basis_schema.get('anyOf', [])
                if not any(v.get('type') == 'object' and v.get('additionalProperties') is False
                           and v.get('required') == ['public_request']
                           and v.get('properties', {}).get('public_request') == {'type': 'boolean', 'const': True}
                           for v in variants):
                    raise ValueError('public basis reference missing from actual Author tool schema')
        parent_gate = bool(self._rubric_mechanical_profile.get('strict_google_sheets_scored_row_parent_identity'))
        if self._rubric_mechanical_profile.get('strict_sales_fiveapp_policy_conditions'):
            from .sales_five_app_profile import GUIDANCE
            source_schema = self.parameters['properties'][self._source_root]
            replacement = source_schema['properties']['policy_fixtures']['items']['properties']['initial_state_replacements']
            if (GUIDANCE not in source_schema['description'] or 'selection_contract' not in source_schema['required']
                    or replacement.get('minProperties') != 1 or replacement.get('maxProperties') != 1):
                raise ValueError('Sales five-app conditions and joins are absent from actual Author schema')
        if self._rubric_mechanical_profile.get('strict_marketing_fiveapp_policy_conditions'):
            from .marketing_five_app_profile import GUIDANCE
            source_schema = self.parameters['properties'][self._source_root]
            replacement = source_schema['properties']['policy_fixtures']['items']['properties']['initial_state_replacements']
            if (GUIDANCE not in source_schema['description'] or 'selection_contract' not in source_schema['required']
                    or replacement.get('minProperties') != 1 or replacement.get('maxProperties') != 1):
                raise ValueError('Marketing five-app conditions and joins are absent from actual Author schema')
        if self._rubric_mechanical_profile.get('strict_hr_fiveapp_policy_conditions'):
            from .hr_five_app_profile import GUIDANCE
            source_schema = self.parameters['properties'][self._source_root]
            replacement = source_schema['properties']['policy_fixtures']['items']['properties']['initial_state_replacements']
            if (GUIDANCE not in source_schema['description'] or 'selection_contract' not in source_schema['required']
                    or replacement.get('minProperties') != 1 or replacement.get('maxProperties') != 1):
                raise ValueError('HR five-app conditions and joins are absent from actual Author schema')
        if self._rubric_mechanical_profile.get('strict_native_join_bridges'):
            from .native_join_bridges import GUIDANCE
            if GUIDANCE not in self.parameters['properties'][self._source_root]['description']:
                raise ValueError('native join bridge gate is absent from actual Author schema')
        if self._rubric_mechanical_profile.get('strict_fiveapp_output_source_selection'):
            from .five_app_outcome_sources import GUIDANCE, validate_profile
            validate_profile(self._rubric_mechanical_profile)
            if GUIDANCE not in self.parameters['properties'][self._source_root]['description']:
                raise ValueError('native outcome-source binding is absent from actual Author schema')
        if self._rubric_mechanical_profile.get('strict_marketing_coordinated_status'):
            from .marketing_coordinated_status import GUIDANCE
            if GUIDANCE not in self.parameters['properties'][self._source_root]['description']:
                raise ValueError('coordinated status gate is absent from actual Author schema')
        if self._rubric_mechanical_profile.get('strict_marketing_status_lifecycle'):
            from .marketing_status_lifecycle import GUIDANCE
            if GUIDANCE not in self.parameters['properties'][self._source_root]['description']:
                raise ValueError('lifecycle gate is absent from actual Author schema')
        if parent_gate and 'original worksheet identity' not in self.parameters['properties'][self._source_root]['properties']['native_construction_cases']['description']:
            raise ValueError('worksheet parent gate is not advertised in the actual Author schema')
        return {"source_root": self._source_root,
                **({'sales_fiveapp_gate': {'enabled': True, 'selection_contract_required': True,
                    'contract': self._rubric_mechanical_profile['sales_fiveapp_contract'],
                    'semantic_correctness_still_requires_review': True}}
                    if self._rubric_mechanical_profile.get('strict_sales_fiveapp_policy_conditions') else {}),
                **({'marketing_fiveapp_gate': {'enabled': True, 'selection_contract_required': True,
                    'contract': self._rubric_mechanical_profile['marketing_fiveapp_contract'],
                    'semantic_correctness_still_requires_review': True}}
                    if self._rubric_mechanical_profile.get('strict_marketing_fiveapp_policy_conditions') else {}),
                **({'hr_fiveapp_gate': {'enabled': True, 'selection_contract_required': True,
                    'contract': self._rubric_mechanical_profile['hr_fiveapp_contract'],
                    'semantic_correctness_still_requires_review': True}}
                    if self._rubric_mechanical_profile.get('strict_hr_fiveapp_policy_conditions') else {}),
                "worksheet_parent_gate": {"enabled": parent_gate,
                    "contract": native_cases.WORKSHEET_PARENT_CONTRACT,
                    "scope": "parents of native google_sheets_row_cell_equals witnesses only",
                    "other_container_semantics_still_require_review": True},
                "public_text_gate_scope_contract": "assertion-text-field-presentation-and-record-label-scope-v2",
                "native_construction_case_contract": native_cases.CONTRACT,
                "public_basis_reference_contract": native_cases.PUBLIC_BASIS_CONTRACT,
                "required_native_construction_case_categories": self._rubric_mechanical_profile.get(
                    'required_native_construction_case_categories', []),
                "case_semantic_completeness_requires_independent_review": True,
                "construction_application_role_gate": {
                    "contract":self._rubric_mechanical_profile.get('construction_application_roles'),
                    "minimum_background_records":self._rubric_mechanical_profile.get('minimum_non_target_background_records',0),
                    "minimum_counterfactual_join_pairs":self._rubric_mechanical_profile.get('minimum_cross_application_joins',0),
                    "minimum_independent_policy_facts":self._rubric_mechanical_profile.get('minimum_independent_policy_facts',0),
                    "necessity_is_not_assertion_membership":True},
                "native_seed_read_witness_contract": NATIVE_SEED_READ_WITNESS_CONTRACT,
                **({'native_join_bridge_gate': {'enabled': True,
                    'contract': self._rubric_mechanical_profile['native_join_bridge_contract'],
                    'semantic_correctness_still_requires_review': True}}
                    if self._rubric_mechanical_profile.get('strict_native_join_bridges') else {}),
                "compact_official_task_source": self._compact_official_task_source,
                "policy_fixture_gate_required": bool(self._rubric_mechanical_profile.get("strict_opposite_policy_fixture")),
                "minimum_policy_fixture_count": self._rubric_mechanical_profile.get("strict_minimum_policy_fixtures", 1),
                **({'marketing_coordinated_status_gate':{'enabled':True,
                    'contract':self._rubric_mechanical_profile['marketing_coordinated_status_contract'],
                    'minimum_targets':2,'maximum_targets':3,'exact_siblings':2}}
                    if self._rubric_mechanical_profile.get('strict_marketing_coordinated_status') else {}),
                **({'native_policy_fact_value_projection':'official-world-json-scalar-v1'}
                    if self._rubric_mechanical_profile.get('strict_native_fact_json_projection') else {}),
                **({'marketing_status_lifecycle_gate': {'enabled': True,
                    'contract': self._rubric_mechanical_profile['marketing_status_lifecycle_contract'],
                    'all_construction_programs_checked': True, 'minimum_coupled_target_outcomes': 2}}
                    if self._rubric_mechanical_profile.get('strict_marketing_status_lifecycle') else {}),
                **({"independent_readable_policy_fact_gate": {
                    "enabled": True,
                    "contract": self._rubric_mechanical_profile['independent_policy_fact_contract']}}
                    if self._rubric_mechanical_profile.get('strict_independent_readable_policy_facts') else {}),
                **({'multi_app_native_dependency_gate': {'enabled': True,
                    'contract': self._rubric_mechanical_profile['multi_app_dependency_contract'],
                    'application_count': 5, 'minimum_relationship_pairs': 3,
                    'minimum_fixture_count': 5, 'maximum_fixture_count': 12,
                    'single_scalar_per_fixture': bool(self._rubric_mechanical_profile.get('strict_single_scalar_dependency_intervention')),
                    'semantic_fidelity_requires_independent_review': True}}
                    if self._rubric_mechanical_profile.get('strict_five_app_native_dependencies') else {}),
                "tool_schema_sha256": _sha(self.parameters)}

    def _selection_outcome_sources(self, instruction, initial_state, actions, assertions):
        if not self._rubric_mechanical_profile.get('strict_fiveapp_output_source_selection'):
            return frozenset()
        from .five_app_outcome_sources import witnessed_sources
        return witnessed_sources(instruction=instruction, initial_state=initial_state,
            oracle_actions=actions, assertions=assertions)

    def _save_draft(self, candidate: str, source: Mapping[str, Any]) -> str:
        revision = _sha({
            "candidate_markdown": candidate,
            self._source_root: source,
        })
        self._draft_candidate_markdown = candidate
        self._draft_task_source = copy.deepcopy(dict(source))
        self._draft_revision_sha256 = revision
        return revision


    def _normalize_mechanical_candidate(self, parsed: dict) -> dict:
        """Delegate to the one shared normalisation implementation.

        The production Author reaches the gate through two classes; both call
        ``author_mechanics.normalize`` so a fix can never again land in only one of
        them (measured 2026-09-15: 27 basis and 15 repair-key rejections in a single
        wave while the other class already normalised them).
        """
        from . import author_mechanics
        try:
            from .agentic_runtime_compiler import extract_task_request
        except Exception:
            extract_task_request = None
        obligations = [o.get('obligation_id') for o in
                       ((getattr(self, '_construction_role_context', None) or {}).get('construction') or {}).get('obligations') or []]
        notes = author_mechanics.normalize(
            parsed,
            draft_task_source=getattr(self, '_draft_task_source', None),
            candidate_markdown=(getattr(self, '_draft_candidate_markdown', None) or str(parsed.get('candidate_markdown') or '')),
            construction_obligations=obligations,
            extract_task_request=extract_task_request,
            construction=(getattr(self, '_construction_role_context', None) or {}).get('construction'),
        )
        if notes:
            ledger = list(getattr(self, 'mechanical_normalizations', []) or [])
            ledger.append(notes)
            try:
                setattr(self, 'mechanical_normalizations', ledger)
            except Exception:
                pass
        return parsed

    def _journal_compile_attempt(self, result: dict) -> None:
        """Persist this attempt on the live path (O_APPEND + fsync, bounded)."""
        try:
            import hashlib as _hashlib, os as _os, time as _time
            from pathlib import Path as _Path
            directory = _os.environ.get('UBE_TOOL_TIMING_DIR')
            if not directory:
                return
            path = _Path(directory) / 'compile_attempts.jsonl'
            path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                'schema_version': 'construction-compile-attempt-journal-v1',
                'observed_at_epoch': _time.time(),
                'observed_at_cst': _time.strftime('%Y-%m-%d %H:%M:%S', _time.localtime()),
                'root_task_id': self._candidate_id,
                'accepted': bool(result.get('accepted')),
                'error_type': result.get('error_type'),
                'error': (str(result.get('error'))[:4000] if result.get('error') else None),
                'traceback': (str(result.get('traceback'))[-8000:] if result.get('traceback') else None),
                'draft_revision_sha256': result.get('draft_revision_sha256'),
                'mechanical_normalizations': getattr(self, 'mechanical_normalizations', None),
            }
            line = (json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + '\n').encode('utf-8')
            handle = _os.open(path, _os.O_APPEND | _os.O_CREAT | _os.O_WRONLY, 0o664)
            try:
                _os.write(handle, line)
                _os.fsync(handle)
            finally:
                _os.close(handle)
        except Exception:
            return

    @evidence_scope
    def call(self, params: Mapping[str, Any] | str, **_: Any) -> str:
        self.call_count += 1
        # Queue 0018: everything before the first official scorer call is a
        # zero-execution rejection.  The outer Author interface refunds the (1+2)
        # compile budget for those, so this marker must not depend on the
        # exception coming from a staged validator: a plain ValueError from an
        # earlier shape/scope check spent a repair attempt exactly the same way
        # (measured 2026-09-15: 'JSON pointer ... does not resolve', 'candidate QA
        # Markdown contains content outside the business-workflow scope').
        self._official_execution_started = False
        # Initialised at the top so the failure receipt can always name them, even
        # when the submission dies before the validation block is reached.
        reviewer_signals: list[dict[str, Any]] = []
        pre_execution_diagnostics: list[dict[str, Any]] = []
        # Class-(3) findings (policy fixtures / join witnesses / read probes and
        # the order-leakage heuristics) are internal *format* observations.  They
        # are neither a hard gate nor a Reviewer judgement - the independent
        # Reviewer has nothing meaningful to say about "our fixture schema" - so
        # they are recorded here for the builder/controller to enforce, and they
        # must never enter the repair loop.
        builder_contract_findings: list[dict[str, Any]] = []
        statistic_only_advisories: list[str] = []
        try:
            parsed = json.loads(params) if isinstance(params, str) else dict(params)
            parsed = self._normalize_mechanical_candidate(parsed)
            if self._turn_index_getter is not None:
                turn_index = int(self._turn_index_getter())
                if turn_index == self._last_compile_turn:
                    raise ValueError(
                        "only one stateful compile_and_test_task_package call is allowed per "
                        "assistant turn; consume the complete result before the next repair"
                    )
                self._last_compile_turn = turn_index
            if self._require_semantic_graph:
                parsed, folded_count = _fold_provider_flattened_semantic_fields(parsed)
                self.provider_flattened_semantic_field_count += folded_count
            if self._compact_official_task_source and "semantic_graph" in parsed:
                raise ValueError(
                    "compact official lineage requires task_source; semantic_graph is forbidden"
                )
            if self._compact_official_task_source:
                parsed, compact_normalization = (
                    _fold_provider_flattened_compact_task_source(parsed)
                )
                for kind, count in compact_normalization.items():
                    self.compact_source_provider_normalization_by_kind[kind] += count
                    self.compact_source_provider_normalization_count += count
            source_root = self._source_root
            supplied_patch = parsed.get("repair_patch")
            supplied_fields = parsed.get("repair_fields")
            if self._require_semantic_graph and supplied_patch is not None:
                raise ValueError(
                    "semantic_graph lineage forbids legacy repair_patch; use hash-bound "
                    "top-level repair_fields"
                )
            if supplied_patch is not None and supplied_fields is not None:
                raise ValueError("repair calls must use exactly one of repair_fields or repair_patch")
            if supplied_patch is not None or supplied_fields is not None:
                if supplied_fields is not None:
                    self.repair_fields_count += 1
                else:
                    self.repair_patch_count += 1
                if (
                    parsed.get("candidate_markdown") is not None
                    or parsed.get("task_source") is not None
                    or parsed.get("semantic_graph") is not None
                ):
                    raise ValueError("repair calls must not mix repairs with a full replacement")
                if self._draft_candidate_markdown is None or self._draft_task_source is None:
                    raise ValueError("a repair requires one prior full draft submission")
                base_revision = str(parsed.get("base_revision_sha256") or "")
                if base_revision != self._draft_revision_sha256:
                    expected_revision = str(self._draft_revision_sha256 or "")
                    single_nibble_typo = _is_single_nibble_sha256_typo(
                        base_revision,
                        expected_revision,
                    )
                    if not single_nibble_typo:
                        raise ValueError(
                            "base_revision_sha256 does not match the latest draft; refresh from the "
                            "most recent compile result before repairing"
                        )
                    # A one-nibble transcription error cannot identify a stale SHA-256
                    # revision in practice. Bind it to the sole current in-memory draft and
                    # retain an explicit audit counter; all semantic and native gates rerun.
                    self.base_revision_single_nibble_correction_count += 1
                document = {
                    "candidate_markdown": self._draft_candidate_markdown,
                    source_root: self._draft_task_source,
                }
                draft = (
                    _apply_author_repair_fields(
                        document,
                        supplied_fields,
                        source_root=source_root,
                    )
                    if supplied_fields is not None
                    else _apply_author_repair_patch(
                        document,
                        supplied_patch,
                        source_root=source_root,
                    )
                )
                candidate = str(draft.get("candidate_markdown") or "").strip()
                source_value = draft.get(source_root)
                # A sibling parameter supplied through repair_fields must reach
                # exactly the places a full submission would have put it.
                for sibling in _SIBLING_REPAIR_FIELDS:
                    if sibling not in draft:
                        continue
                    parsed[sibling] = draft[sibling]
                    if sibling == "construction_application_roles":
                        context = getattr(self, "_construction_role_context", None)
                        if isinstance(context, Mapping):
                            updated = dict(context)
                            updated["roles"] = draft[sibling]
                            self._construction_role_context = updated
            else:
                self.full_submission_count += 1
                if parsed.get("base_revision_sha256") is not None:
                    raise ValueError("base_revision_sha256 is only valid with a repair")
                candidate = str(parsed.get("candidate_markdown") or "").strip()
                if self._require_semantic_graph and parsed.get("task_source") is not None:
                    raise ValueError(
                        "this immutable lineage requires semantic_graph; direct task_source is forbidden"
                    )
                if not self._require_semantic_graph and parsed.get("semantic_graph") is not None:
                    raise ValueError(
                        "this legacy lineage requires task_source; semantic_graph is not enabled"
                    )
                source_value = parsed.get(source_root)
            if not isinstance(source_value, Mapping):
                raise TypeError(f"{source_root} must be an object")
            if self._require_semantic_graph:
                source_value, normalization = (
                    _canonicalize_redundant_semantic_graph_projections(source_value)
                )
                for kind, count in normalization.items():
                    self.deterministic_semantic_projection_normalization_by_kind[kind] += count
                    self.deterministic_semantic_projection_normalization_count += count
            validate_candidate_qa_markdown(candidate)
            instruction = extract_task_request(candidate)
            if self._compact_official_task_source:
                # candidate_markdown is the sole Author-owned public instruction.  Keeping a
                # second editable copy in task_source created byte-drift failures and let repairs
                # move the two representations independently.  Derive the runtime projection
                # deterministically before hashing/saving every full or repaired draft.
                compact_source = copy.deepcopy(dict(source_value))
                if "task_instruction" in compact_source:
                    compact_source.pop("task_instruction")
                    self.compact_source_redundant_task_instruction_drop_count += 1
                compact_source["task_instruction"] = instruction
                source_value = compact_source
                self.compact_source_task_instruction_derivation_count += 1
                state_value = compact_source.get("initial_state")
                if isinstance(state_value, Mapping):
                    normalized_state, folded_actions = _normalize_top_level_action_ledger(
                        state_value
                    )
                    if folded_actions:
                        compact_source["initial_state"] = normalized_state
                        source_value = compact_source
                        self.compact_source_action_ledger_fold_count += folded_actions
                    normalized_state, wrapped = _normalize_single_permitted_app_local_state(
                        normalized_state,
                        self._rubric_mechanical_profile.get("permitted_applications"),
                    )
                    if wrapped:
                        compact_source["initial_state"] = normalized_state
                        source_value = compact_source
                        self.compact_source_single_app_local_state_wrap_count += wrapped
                selection_value = compact_source.get("selection_contract")
            draft_revision = self._save_draft(candidate, source_value)
            source = (
                semantic_graph_to_task_source(source_value)
                if self._require_semantic_graph
                else copy.deepcopy(dict(source_value))
            )
            if OFFICIAL_RELEASE == 'the pinned runtime':
                if isinstance(source.get('initial_state'), dict):
                    source['initial_state'] = normalize_runtime_value(source['initial_state'])
                if isinstance(source.get('assertions'), list):
                    source['assertions'] = [normalize_runtime_value(a) for a in source['assertions']]
            allowed_source_keys = {
                "task_instruction",
                "initial_state",
                "assertions",
                "oracle_actions",
                "forbidden_extra_actions",
                "scorer_counterexample_tests",
                "policy_fixtures",
                "native_construction_cases",
                "tool_names",
            }
            initial_state = source.get("initial_state")
            assertions = source.get("assertions")
            actions = source.get("oracle_actions")
            forbidden_extra_actions = source.get("forbidden_extra_actions")
            scorer_counterexample_tests = source.get("scorer_counterexample_tests")
            scorer_obligation_ledger = source.get("scorer_obligation_ledger")
            state_surface_manifest = source.get("state_surface_manifest")
            contract_closure_manifest = source.get("contract_closure_manifest")
            selection_contract = source.get("selection_contract")
            policy_fixtures = source.get("policy_fixtures")
            construction_cases = source.get('native_construction_cases')
            tool_names = source.get("tool_names") or []
            application_role_check=None
            application_role_native_evidence=None
            # User directive 2026-09-15 14:28: a submission must report *every*
            # pre-execution gate it fails, not just the first.  The staged
            # validators already batch the checks inside one stage; the loss was
            # between stages (a structural rejection hid all 39 static-contract
            # gates) and on the direct raises in this block.  Collect them and
            # raise one merged diagnostic set before any official execution.
            pre_execution_diagnostics: list[dict[str, Any]] = []
            # Class-(2) gate findings are reported here instead of rejecting the
            # submission (see the split below); the independent Reviewer decides.
            reviewer_signals: list[dict[str, Any]] = []

            def collect_stage(stage: str, checks) -> bool:
                try:
                    _run_validation_stage(stage, checks)
                except _StagedTaskValidationError as stage_error:
                    pre_execution_diagnostics.extend(
                        dict(row, stage=stage) for row in getattr(stage_error, "errors", [])
                    )
                    return True
                return False

            def collect_direct(gate: str, call) -> None:
                try:
                    call()
                except Exception as error:  # noqa: BLE001 - reported as a diagnostic
                    pre_execution_diagnostics.append({
                        "code": gate,
                        "stage": "pre_execution",
                        "error_type": type(error).__name__,
                        "message": str(error)[:4_000],
                    })

            if self._rubric_mechanical_profile.get('construction_application_roles'):
                from .construction_application_roles import validate_roles
                context=getattr(self,'_construction_role_context',None)
                if not context:
                    # Controller delivery (2026-09-16): the Author does not declare roles and
                    # does not instantiate assets, so there is no bound context to require.
                    # Derive the split from the compiled task plus the cell profile and enforce
                    # only the per-cell application contract.
                    context={'roles':None,'construction':None}
                collect_direct(
                    "construction_application_roles",
                    lambda: setattr(
                        self, "_collected_role_check",
                        # 2026-09-16 ruling: the Author no longer declares the role split.
                        # Passing `None` makes `validate_roles` derive it mechanically from
                        # (initial_state, assertions, oracle_actions) and then enforce the
                        # per-cell application contract on the derived facts.  A legacy
                        # lineage that still submits a declaration has it ignored here
                        # rather than trusted.
                        validate_roles(None,context['construction'],source,
                                       self._rubric_mechanical_profile),
                    ),
                )
                application_role_check=getattr(self,'_collected_role_check',None)
            collect_stage(
                "task_source_structure",
                [
                    (
                        "allowed_source_keys",
                        lambda: _require_condition(
                            not (set(source) - allowed_source_keys),
                            "unsupported task_source keys: "
                            + ", ".join(sorted(set(source) - allowed_source_keys)),
                        ),
                    ),
(
                        "task_instruction_exact",
                        lambda: _require_condition(
                            source.get("task_instruction") == instruction,
                            "task_source.task_instruction must exactly match the public task request",
                        ),
                    ),
                    (
                        "initial_state",
                        lambda: _require_condition(
                            isinstance(initial_state, dict) and bool(initial_state),
                            "initial_state must be a non-empty object",
                        ),
                    ),
                    (
                        "assertions",
                        lambda: _require_condition(
                            isinstance(assertions, list) and len(assertions) >= 3,
                            "at least three official assertions are required",
                        ),
                    ),
                    (
                        "oracle_actions",
                        lambda: _require_condition(
                            isinstance(actions, list) and bool(actions),
                            "oracle_actions must provide a full-credit official API path",
                        ),
                    ),
                    (
                        "forbidden_extra_actions",
                        lambda: _require_condition(
                            isinstance(forbidden_extra_actions, list)
                            and len(forbidden_extra_actions) >= 2,
                            "at least two forbidden_extra_actions are required to test over-completion",
                        ),
                    ),
                    (
                        "tool_names",
                        lambda: _require_condition(
                            isinstance(tool_names, list)
                            and all(isinstance(x, str) for x in tool_names),
                            "tool_names must be a string list",
                        ),
                    ),
                    (
                        "rubric_mechanical_profile",
                        lambda: _validate_rubric_mechanical_profile(
                            profile=self._rubric_mechanical_profile,
                            instruction=instruction,
                            initial_state=initial_state,
                            assertions=assertions,
                            application_roles=getattr(self,'_construction_role_context',None),
                        ),
                    ),
                    (
                        "scorer_counterexample_tests",
                        lambda: _require_condition(
                            not self._require_scorer_counterexamples
                            or scorer_counterexample_tests is not None,
                            "scorer_counterexample_tests are required by this author lineage",
                        ),
                    ),
                    (
                        "policy_fixtures",
                        lambda: _require_condition(
                            not self._rubric_mechanical_profile.get("strict_opposite_policy_fixture")
                            or isinstance(policy_fixtures, list) and bool(policy_fixtures),
                            "Rubric requires executable policy_fixtures; a Markdown promise is insufficient",
                        ),
                    ),
                    (
                        'native_construction_cases',
                        lambda: _require_condition(
                            not self._rubric_mechanical_profile.get('required_native_construction_case_categories')
                            or isinstance(construction_cases, list) and len(construction_cases) >= len(
                                self._rubric_mechanical_profile['required_native_construction_case_categories']),
                            'Rubric requires executable native_construction_cases; a prose promise is insufficient'),
                    ),
],
            )
            public_observability_advisories = _public_observability_advisories(
                instruction,
                assertions,
            )

            official = _official_imports()
            WorldState = official["WorldState"]
            registry = official["AssertionRegistry"]
            registered_assertions = sorted(registry._handlers)  # noqa: SLF001

            def validate_world_state() -> None:
                seeded_services = sorted(key for key in initial_state if key != "meta")
                unknown_services = sorted(
                    set(seeded_services) - set(WorldState.model_fields)
                )
                if unknown_services:
                    raise ValueError(f"unknown WorldState services: {unknown_services}")
                if not seeded_services:
                    raise ValueError("a matched task must seed at least one official service")
                if (
                    isinstance(initial_state.get("meta"), dict)
                    and "allowed_services" in initial_state["meta"]
                ):
                    raise ValueError(
                        "author must not set meta.allowed_services; the official runner derives it"
                    )
                WorldState(**normalize_runtime_value(copy.deepcopy(initial_state)))

            def validate_assertion_symbol(index: int, assertion: Any) -> None:
                if not isinstance(assertion, dict) or not isinstance(assertion.get("type"), str):
                    raise ValueError(f"assertions[{index}] must be an object with type")
                assertion_type = assertion["type"]
                if assertion_type not in registry._handlers:  # noqa: SLF001
                    suggestions = difflib.get_close_matches(
                        assertion_type,
                        registered_assertions,
                        n=8,
                        cutoff=0.45,
                    )
                    raise ValueError(
                        f"unknown official assertion type: {assertion_type}; "
                        f"closest registered types={suggestions}"
                    )

            # These checks are independent once the compact source has passed the
            # coarse type/required-field gate.  Returning them as one diagnostic
            # batch avoids making the Author repair one layer per provider turn;
            # no acceptance criterion is removed or weakened.
            static_native_checks: list[tuple[str, Callable[[], None]]] = [
                    (
                        f"assertion_{index:03d}",
                        lambda index=index, assertion=assertion: validate_assertion_symbol(
                            index, assertion
                        ),
                    )
                    for index, assertion in enumerate(assertions)
                ]

            def validate_action_shape(
                label: str,
                index: int,
                action: Any,
                *,
                require_state_change: bool,
            ) -> None:
                if not isinstance(action, Mapping):
                    raise TypeError(f"{label}[{index}] must be an object")
                if set(action) - {"method", "url", "params", "body"}:
                    raise ValueError(f"{label}[{index}] has unsupported keys")
                method = str(action.get("method") or ("" if require_state_change else "GET")).upper()
                url = str(action.get("url") or "")
                if not url:
                    raise ValueError(f"{label}[{index}].url is required")
                if require_state_change and method in {"", "GET", "HEAD", "OPTIONS"}:
                    raise ValueError(f"{label}[{index}] must be state-changing")

            static_native_checks.extend(
                [
                    *[
                        (
                            f"oracle_action_{index:03d}",
                            lambda index=index, action=action: validate_action_shape(
                                "oracle_actions",
                                index,
                                action,
                                require_state_change=False,
                            ),
                        )
                        for index, action in enumerate(actions)
                    ],
                    *[
                        (
                            f"forbidden_extra_action_{index:03d}",
                            lambda index=index, action=action: validate_action_shape(
                                "forbidden_extra_actions",
                                index,
                                action,
                                require_state_change=True,
                            ),
                        )
                        for index, action in enumerate(forbidden_extra_actions)
                    ],
                ]
            )
            if self._compact_official_task_source:
                static_native_checks.append(
                    (
                        "compact_google_sheets_write_surface",
                        lambda: _validate_compact_google_sheets_write_surface(actions),
                    )
                )
            static_native_checks.extend(
                [
("action_assertion_shape", lambda: _validate_action_assertion_shape(assertions)),
                    ("native_action_guard_representation", lambda: _validate_native_action_guard_representation(assertions, initial_state)),
(
                        "public_observability_contract",
                        lambda: _validate_public_observability_contract(instruction, assertions),
                    ),
(
                        "known_native_enum_values",
                        lambda: _validate_known_native_enum_values(initial_state, assertions),
                    ),
                    (
                        "append_serialization_contract",
                        lambda: _validate_append_serialization_contract(
                            instruction, assertions, initial_state
                        ),
                    ),
                ]
            )
            static_native_checks.extend(
                [
                    ("official_world_state", validate_world_state),
]
            )
            # Class split (user + supervisor directive 2026-09-15 14:28/14:45).
            # The calibration runs on the official 600 (supervisor §65/§66)
            # separate two kinds of gate:
            #   (1) gates about the *task itself* - official vocabulary, world
            #       state, exactness, bounded preservation, the 1500-character
            #       limit - measured false-positive rate 0.0-0.6% on the official
            #       600, so they stay hard;
            #   (2) gates about *our own intermediate artefacts* - policy
            #       fixtures, join witnesses, reset-read probes, cross-world
            #       alternates, selection contracts, presentation-order
            #       heuristics.  Official tasks have no such fields at all, so
            #       these can never be calibrated against the published contract;
            #       they are recorded as Reviewer signals instead of rejecting
            #       the submission.  Measured 2026-09-15: the two biggest codes
            #       here (strict_named_gate_causal_services 757,
            #       strict_native_evidence_readability 733) were ~40% of all
            #       rejections and are exactly the "project-specific benchmark"
            #       the repository's own advisory docstring warns about.
            collect_stage("static_native_contract", static_native_checks)
            for code, check in static_advisory_checks:
                try:
                    check()
                except Exception as advisory_error:  # noqa: BLE001 - signal, not a gate
                    builder_contract_findings.append({
                        "code": code,
                        "stage": "static_native_contract_advisory",
                        "disposition": "builder_enforced_not_a_quality_judgement",
                        "message": str(advisory_error)[:2_000],
                    })
            if pre_execution_diagnostics:
                # One receipt names every failed gate from both pre-execution
                # stages plus the direct role checks, so one repair turn can fix
                # all of them instead of only the first.  Identical messages reported
                # under several codes are merged, and every row is labelled with its
                # gate class (supervisor 2026-09-15 §97).
                raise _StagedTaskValidationError(
                    "pre_execution", _merge_pre_execution_diagnostics(pre_execution_diagnostics)
                )
            lifecycle_result = None
            if self._rubric_mechanical_profile.get('strict_marketing_status_lifecycle'):
                from .marketing_status_lifecycle import validate_source
                lifecycle_result = validate_source(initial_state=initial_state, assertions=assertions,
                    oracle_actions=actions, fixtures=policy_fixtures, cases=construction_cases,
                    forbidden_extra_actions=forbidden_extra_actions,
                    scorer_counterexample_tests=scorer_counterexample_tests, instruction=instruction)
            world = WorldState(**normalize_runtime_value(copy.deepcopy(initial_state)))
            coordinated_reset_campaigns = (
                copy.deepcopy(world.google_ads.campaigns)
                if self._rubric_mechanical_profile.get("strict_marketing_coordinated_status")
                else None
            )
            selection_contract_result = (
                _removed_gate(
                    initial_state=initial_state,
                    oracle_actions=actions,
                    contract=selection_contract,
                    outcome_source_services=self._selection_outcome_sources(
                        instruction, initial_state, actions, assertions),
                )
                if isinstance(selection_contract, Mapping)
                else None
            )
            if isinstance(selection_contract, Mapping):
                _removed_gate(
                    instruction=instruction,
                    contract=selection_contract,
                )
            service_fields = sorted(
                (str(field) for field in WorldState.model_fields if field != "meta"),
                key=len,
                reverse=True,
            )
            world.meta.allowed_services = _compute_allowed_services(
                initial_state=initial_state,
                assertions=assertions,
                tool_names=tool_names,
                service_fields=service_fields,
            )
            # First official execution of this compile turn: from here on a
            # rejection has actually spent an official regression, so the outer
            # interface stops refunding the Author's (1+2) budget.
            self._official_execution_started = True
            no_action = _official_score(
                initial_state=initial_state,
                assertions=assertions,
                world=copy.deepcopy(world),
            )
            if no_action["strict_pass"]:
                raise ValueError("official scorer gives full credit to the no-action state")

            oracle_initial_world = copy.deepcopy(world)
            oracle_responses,mutation_count=_execute_official_action_sequence(
                official=official,world=world,actions=actions,label='oracle')
            minimum_effect_calls=int(self._rubric_mechanical_profile.get('minimum_business_effect_calls',
                1 if application_role_check else 2))
            if mutation_count < minimum_effect_calls:
                raise ValueError('oracle has fewer actual state-changing business operations than the executed profile requires: '
                    +str(mutation_count)+' < '+str(minimum_effect_calls))
            final_score = _official_score(
                initial_state=initial_state,
                assertions=assertions,
                world=world,
            )
            if not final_score["strict_pass"]:
                diagnostic = {
                    "recorded_action_candidates": _recorded_action_candidates(
                        world=world,
                        assertions=assertions,
                        service_fields=service_fields,
                    ),
                    "score": final_score,
                }
                raise ValueError(
                    "oracle path does not reach official full credit: "
                    + _canonical(diagnostic)[:12_000]
                )
            if application_role_check:
                from .construction_application_roles import oracle_operation_evidence,verify_effect_roles
                operation_rows,role_world=oracle_operation_evidence(initial_state,actions,assertions)
                application_role_native_evidence={
                    'role_check':application_role_check,'operations':operation_rows,
                    'effect_checks':verify_effect_roles(application_role_check,initial_state,assertions,operation_rows,role_world)}
                if application_role_check['roles'].get('non_target_records'):
                    from .task_background_records import run_records
                    application_role_native_evidence['task_background_records']=run_records(
                        application_role_check['roles']['non_target_records'],initial_state,assertions,role_world)
                if self._rubric_mechanical_profile.get('strict_named_gate_causal_services'):
                    application_role_native_evidence['causal_services']=_removed_gate(
                        instruction=instruction,initial_state=initial_state,oracle_actions=actions,assertions=assertions,
                        application_roles=application_role_check,policy_fixtures=policy_fixtures,
                        minimum_source_services=int(self._rubric_mechanical_profile.get('strict_minimum_private_evidence_sources',1)),
                        require_unique_source_values=bool(self._rubric_mechanical_profile.get('strict_unique_private_evidence_values')))
                elif application_role_check['roles']['necessary_evidence_applications']:
                    raise ValueError('declared necessary evidence has no enabled causal execution gate')
                if self._rubric_mechanical_profile.get('strict_native_evidence_readability'):
                    application_role_native_evidence['readability']=_removed_gate(
                        instruction=instruction,initial_state=initial_state,oracle_actions=actions,assertions=assertions,
                        application_roles=application_role_check,policy_fixtures=policy_fixtures,
                        minimum_source_services=int(self._rubric_mechanical_profile.get('strict_minimum_private_evidence_sources',1)))
            post_oracle_results: dict[str, Any] = {
                "repeatable_oracle_collection_sensitivity": {
                    "repeat_growth_test_count": 0,
                    "duplicate_closed_or_idempotent_count": 0,
                },
                "central_non_target_field_sensitivity": {
                    "candidate_field_count": 0,
                    "tested_field_count": 0,
                    "schema_reconstruction_skip_count": 0,
                },
                "changed_selected_identity_sensitivity": {
                    "candidate_text_leaf_count": 0,
                    "tested_text_leaf_count": 0,
                },
                "grown_collection_seed_preservation": {
                    "grown_collection_count": 0,
                    "candidate_field_count": 0,
                    "tested_field_count": 0,
                    "schema_reconstruction_skip_count": 0,
                },
            }

            def capture_post_oracle_result(key: str, check: Callable[[], Any]) -> None:
                post_oracle_results[key] = check()

            def validate_forbidden_extra_actions() -> list[dict[str, Any]]:
                results: list[dict[str, Any]] = []
                for index, action in enumerate(forbidden_extra_actions):
                    if not isinstance(action, Mapping):
                        raise ValueError(
                            f"forbidden_extra_actions[{index}] must be an object"
                        )
                    if set(action) - {"method", "url", "params", "body"}:
                        raise ValueError(
                            f"forbidden_extra_actions[{index}] has unsupported keys"
                        )
                    method = str(action.get("method") or "").upper()
                    url = str(action.get("url") or "")
                    if method in {"", "GET", "HEAD", "OPTIONS"} or not url:
                        raise ValueError(
                            f"forbidden_extra_actions[{index}] must be state-changing"
                        )
                    adversarial_world = copy.deepcopy(world)
                    params_value = action.get("params")
                    body_value = action.get("body")
                    params_text = (
                        _canonical(params_value)
                        if isinstance(params_value, Mapping)
                        else params_value
                    )
                    body_text = (
                        _canonical(body_value)
                        if isinstance(body_value, Mapping)
                        else body_value
                    )
                    response_text = official["api_fetch"](
                        adversarial_world,
                        method,
                        url,
                        params=params_text,
                        body=body_text,
                    )
                    try:
                        response_value = json.loads(response_text)
                    except json.JSONDecodeError as exc:
                        raise ValueError(
                            f"forbidden extra action {index} returned non-JSON"
                        ) from exc
                    if (
                        isinstance(response_value, dict)
                        and response_value.get("error") is not None
                    ):
                        raise ValueError(
                            f"forbidden extra action {index} is not an executable negative test: "
                            + _canonical(response_value)[:6_000]
                        )
                    adversarial_score = _official_score(
                        initial_state=initial_state,
                        assertions=assertions,
                        world=adversarial_world,
                    )
                    if adversarial_score["strict_pass"]:
                        raise ValueError(
                            f"forbidden extra action {index} still receives official full credit; "
                            "choose a mutation violating an existing public obligation and verify its "
                            "native assertion; do not add an unrelated prohibition just to fail this test"
                        )
                    results.append(
                        {
                            "index": index,
                            "method": method,
                            "url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
                            "response_sha256": hashlib.sha256(
                                response_text.encode("utf-8")
                            ).hexdigest(),
                            "strict_pass": False,
                            "partial_credit": adversarial_score["partial_credit"],
                        }
                    )
                return results

            post_oracle_checks: list[tuple[str, Callable[[], None]]] = [
(
                    "forbidden_extra_actions",
                    lambda: capture_post_oracle_result(
                        "forbidden_extra_actions", validate_forbidden_extra_actions
                    ),
                ),
            ]
            minimum_meaningful_changes = self._rubric_mechanical_profile.get(
                "strict_minimum_meaningful_state_changes"
            )
            if isinstance(minimum_meaningful_changes, int):
                post_oracle_checks.append(
)
            if self._compact_official_task_source:
                post_oracle_checks.extend(
                    [
]
                )
            if isinstance(selection_contract, Mapping):
                post_oracle_checks.append(
)
            _run_validation_stage("post_oracle_sensitivity", post_oracle_checks)
            repeatable_oracle_collection_sensitivity = post_oracle_results[
                "repeatable_oracle_collection_sensitivity"
            ]
            oracle_controlled_field_sensitivity = post_oracle_results[
                "oracle_controlled_field_sensitivity"
            ]
            central_non_target_field_sensitivity = post_oracle_results[
                "central_non_target_field_sensitivity"
            ]
            changed_selected_identity_sensitivity = post_oracle_results[
                "changed_selected_identity_sensitivity"
            ]
            grown_collection_seed_preservation = post_oracle_results[
                "grown_collection_seed_preservation"
            ]
            forbidden_extra_results = post_oracle_results["forbidden_extra_actions"]

            scorer_counterexample_results: list[dict[str, Any]] = []
            scorer_obligation_ledger_result: dict[str, Any] | None = None
            state_surface_manifest_result: dict[str, Any] | None = None
            contract_closure_manifest_result: dict[str, Any] | None = None
            if scorer_counterexample_tests is not None:
                if scorer_obligation_ledger is not None:
                    scorer_obligation_ledger_result = _removed_gate(
                        ledger=scorer_obligation_ledger,
                        assertions=assertions,
                        tests=scorer_counterexample_tests,
                        initial_state=initial_state,
                    )
                if state_surface_manifest is not None:
                    state_surface_manifest_result = _removed_gate(
                        manifest=state_surface_manifest,
                        initial_state=initial_state,
                        assertions=assertions,
                        tests=scorer_counterexample_tests,
                        obligation_ledger=scorer_obligation_ledger,
                    )
                if contract_closure_manifest is not None:
                    contract_closure_manifest_result = _removed_gate(
                        manifest=contract_closure_manifest,
                        instruction=instruction,
                        initial_state=initial_state,
                        before_world=oracle_initial_world,
                        oracle_world=world,
                        assertions=assertions,
                        obligation_ledger=scorer_obligation_ledger,
                        state_surface_manifest=state_surface_manifest,
                    )
                scorer_counterexample_results = _run_scorer_counterexample_matrix(
                    official=official,
                    WorldState=WorldState,
                    initial_state=initial_state,
                    assertions=assertions,
                    oracle_actions=actions,
                    oracle_world=world,
                    allowed_services=list(world.meta.allowed_services),
                    tests=scorer_counterexample_tests,
                    minimum_effect_calls=minimum_effect_calls,
                )

            policy_fixture_results = (
                _run_policy_fixtures(initial_state=initial_state, assertions=assertions,
                    oracle_actions=actions, fixtures=policy_fixtures,
                    allowed_services=list(world.meta.allowed_services), instruction=instruction,
                    application_roles=application_role_check,
                    minimum_role_join_pairs=self._rubric_mechanical_profile.get('minimum_cross_application_joins',0),
                    minimum_count=self._rubric_mechanical_profile.get("strict_minimum_policy_fixtures", 1),
                    maximum_count=self._rubric_mechanical_profile.get("strict_maximum_policy_fixtures", 4),
                    require_independent_readable_facts=bool(self._rubric_mechanical_profile.get(
                        'strict_independent_readable_policy_facts')),
                    native_fact_json_projection=bool(self._rubric_mechanical_profile.get(
                        'strict_native_fact_json_projection')),
                    require_coordinated_status=bool(self._rubric_mechanical_profile.get(
                        'strict_marketing_coordinated_status')),
                    require_hr_fiveapp_conditions=bool(self._rubric_mechanical_profile.get(
                        'strict_hr_fiveapp_policy_conditions')),
                    require_marketing_fiveapp_conditions=bool(self._rubric_mechanical_profile.get(
                        'strict_marketing_fiveapp_policy_conditions')),
                    require_sales_fiveapp_conditions=bool(self._rubric_mechanical_profile.get(
                        'strict_sales_fiveapp_policy_conditions')),
                    require_five_app_dependencies=bool(self._rubric_mechanical_profile.get(
                        'strict_five_app_native_dependencies')),
                    require_single_scalar_dependency=bool(self._rubric_mechanical_profile.get(
                        'strict_single_scalar_dependency_intervention')))
                if policy_fixtures is not None else []
            )
            candidate_sha = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
            coordinated_status_result=None
            if self._rubric_mechanical_profile.get('strict_marketing_coordinated_status'):
                from .marketing_coordinated_status import validate as validate_cohort
                coordinated_status_result=validate_cohort(initial_state,assertions,world,actions=actions,
                    reset_campaigns=coordinated_reset_campaigns)
            worksheet_parent_results = (native_cases.run_worksheet_parent_cases(
                initial_state=initial_state, assertions=assertions, oracle_world=world,
                allowed_services=list(world.meta.allowed_services))
                if self._rubric_mechanical_profile.get('strict_google_sheets_scored_row_parent_identity') else None)
            native_case_results = (native_cases.run_cases(
                initial_state=initial_state, assertions=assertions, oracle_actions=actions,
                oracle_world=world, cases=construction_cases,
                allowed_services=list(world.meta.allowed_services), instruction=instruction,
                required_categories=self._rubric_mechanical_profile.get('required_native_construction_case_categories', ()))
                if construction_cases is not None else None)
            if worksheet_parent_results is not None:
                if native_case_results is None:
                    native_case_results = {'contract': native_cases.CONTRACT, 'cases': [], 'case_count': 0}
                native_case_results['worksheet_parent_checks'] = {
                    'contract': native_cases.WORKSHEET_PARENT_CONTRACT,
                    'cases': worksheet_parent_results, 'passed': True,
                    'other_container_semantics_still_require_review': True}
            source.update(
                {
                    "schema_version": OFFICIAL_SOURCE_SCHEMA,
                    "candidate_markdown_sha256": candidate_sha,
                    "official_source_contract": OFFICIAL_SOURCE_CONTRACT,
                }
            )
            source_sha = _sha(source)
            task: dict[str, Any] = {
                "schema_version": OFFICIAL_TASK_SCHEMA,
                "task_id": self._candidate_id,
                "example_id": int(candidate_sha[:12], 16),
                "task": self._candidate_id,
                "prompt": [
                    {"role": "system", "content": PIPELINE_SYSTEM_PROMPT},
                    {"role": "user", "content": instruction},
                ],
                "answer": "",
                "info": {
                    "tool_names": list(tool_names),
                    "initial_state": copy.deepcopy(initial_state),
                    "assertions": copy.deepcopy(assertions),
                    "generation": {
                        "official_source_commit": PIPELINE_SOURCE_COMMIT,
                        "official_runtime_contract": OFFICIAL_RUNTIME_CONTRACT,
                        "official_source_contract_sha256": OFFICIAL_SOURCE_CONTRACT["content_sha256"],
                    },
                },
                "domain_label": self._domain,
                "generation_provenance": {
                    "source_candidate_relative_path": self._candidate_relative_path,
                    "source_candidate_markdown_sha256": candidate_sha,
                    "source_rubric_sha256": self._rubric_sha256,
                    "materializer_source_content_sha256": source_sha,
                    "official_source_commit": PIPELINE_SOURCE_COMMIT,
                    "official_runtime_contract": OFFICIAL_RUNTIME_CONTRACT,
                    "official_source_contract_sha256": OFFICIAL_SOURCE_CONTRACT["content_sha256"],
                    "benchmark_task_instance_used_as_template": False,
                },
            }
            if policy_fixtures is not None:
                task["construction_tests"] = {"policy_fixtures": copy.deepcopy(policy_fixtures),
                                               "solver_visible": False}
            if coordinated_status_result is not None:
                task.setdefault('construction_tests',{'solver_visible':False})['native_coordinated_status']=coordinated_status_result
            if lifecycle_result is not None:
                task.setdefault('construction_tests',{'solver_visible':False})['native_status_lifecycle']=lifecycle_result
            if construction_cases is not None:
                task.setdefault('construction_tests', {'solver_visible': False}).update({
                    'native_construction_cases': copy.deepcopy(construction_cases),
                    'native_case_oracle_actions': copy.deepcopy(actions),
                    'native_case_contract': native_cases.CONTRACT})
            repair_context = getattr(self, 'repair_context', None)
            if repair_context is not None:
                from .qa_repair_context import validate_repaired_task
                validate_repaired_task(task, repair_context)
                task['generation_provenance']['qa_repair_lineage'] = copy.deepcopy(repair_context['lineage'])
            task["content_sha256"] = _sha(task)
            runner = _official_task_compatibility_check(task)
            regression = {
                "schema_version": "native-runtime-regression-receipt-v1",
                "status": "completed",
                "official_runtime_contract": OFFICIAL_RUNTIME_CONTRACT,
                "official_source_contract": OFFICIAL_SOURCE_CONTRACT,
                "result": {
                    "strict_pass": True,
                    "no_action_strict_pass": False,
                    "no_action_partial_credit": no_action["partial_credit"],
                    "oracle_partial_credit": final_score["partial_credit"],
                    "assertion_count": len(assertions),
                    "oracle_call_count": len(actions),
                    "oracle_mutation_count": mutation_count,
                    "native_validation_reuse":evidence_statistics(),
                    "application_role_native_evidence":application_role_native_evidence,
                    "oracle_controlled_field_sensitivity": (
                        oracle_controlled_field_sensitivity
                    ),
                    "central_non_target_field_sensitivity": (
                        central_non_target_field_sensitivity
                    ),
                    "changed_selected_identity_sensitivity": (
                        changed_selected_identity_sensitivity
                    ),
                    "grown_collection_seed_preservation": (
                        grown_collection_seed_preservation
                    ),
                    "repeatable_oracle_collection_sensitivity": (
                        repeatable_oracle_collection_sensitivity
                    ),
                    "selection_contract": selection_contract_result,
                    "public_observability_advisories": public_observability_advisories,
                    # `official_distribution_quality_advisories` and its four heuristics
                    # (public_text_assertion_fidelity, structured-atom bare-contains,
                    # message-fact, seeded_role_label_leakage) were deleted on the
                    # 2026-09-15 ruling: the first is contradicted by 52.7% of the
                    # official corpus, so keeping it would push the Author away from the
                    # official distribution.  The function was removed but these two
                    # receipt keys were left behind, which raised `NameError` on every
                    # ACCEPTED package (measured 2026-09-15: 24/116 tests in
                    # test_official_task_package.py failed for this reason).  Do not
                    # reintroduce the field; a surviving quality signal belongs in
                    # `reviewer_signals`, which the independent Reviewer owns.
                    "official_runner": runner,
                    "oracle_response_bindings": oracle_responses,
                    "forbidden_extra_action_results": forbidden_extra_results,
                    "scorer_counterexample_contract": (
                        SCORER_COUNTEREXAMPLE_CONTRACT
                        if scorer_counterexample_results
                        else None
                    ),
                    "scorer_counterexample_results": scorer_counterexample_results,
                    "policy_fixture_results": policy_fixture_results,
                    "native_construction_case_results": native_case_results,
                    "scorer_obligation_ledger": scorer_obligation_ledger_result,
                    "state_surface_manifest": state_surface_manifest_result,
                    "contract_closure_manifest": contract_closure_manifest_result,
                },
            }
            result = {
                "accepted": True,
                "draft_revision_sha256": draft_revision,
                "candidate_sha256": candidate_sha,
                "runtime_source_sha256": source_sha,
                "compiled_task_content_sha256": task["content_sha256"],
                "assertion_count": len(assertions),
                "oracle_write_call_count": mutation_count,
                "forbidden_extra_action_count": len(forbidden_extra_results),
                "scorer_counterexample_test_count": len(
                    scorer_counterexample_results
                ),
                "scorer_obligation_count": (
                    int(scorer_obligation_ledger_result["obligation_count"])
                    if scorer_obligation_ledger_result is not None
                    else 0
                ),
                "state_surface_leaf_count": (
                    int(state_surface_manifest_result["state_leaf_count"])
                    if state_surface_manifest_result is not None
                    else 0
                ),
                "contract_closure_contract": (
                    contract_closure_manifest_result.get("contract")
                    if contract_closure_manifest_result is not None
                    else None
                ),
                "no_action_strict_pass": False,
                "public_observability_advisories": public_observability_advisories,
                # Deleted with the four distribution heuristics above; see the note on
                # the regression receipt.  Referencing an undefined name here made the
                # success path itself raise, so no package could ever be accepted.
                "full_native_regression": regression["result"],
                "official_runtime_contract": OFFICIAL_RUNTIME_CONTRACT,
                "reviewer_signals": reviewer_signals,
                "builder_contract_findings": builder_contract_findings,
                "distribution_statistics": statistic_only_advisories,
            }
            self.accepted_call_count += 1
            self.latest_candidate_markdown = candidate
            self.latest_runtime_source = source
            self.latest_task = task
            self.latest_regression = regression
            self.latest_result = result
            self._journal_compile_attempt(result)
            return json.dumps(result, ensure_ascii=False, sort_keys=True)
        except Exception as exc:  # noqa: BLE001 - bounded feedback enables agent repair
            result = {
                "accepted": False,
                "error_type": type(exc).__name__,
                "error": str(exc)[:32_000],
                # contract55 ramped390: 44 of 62 official-stage compile attempts
                # returned accepted=false with a bare KeyError(<application name>)
                # and no location, because only str(exc) was recorded. Persist the
                # real traceback so the acceptance-path crash is attributable
                # instead of being re-diagnosed from the application name alone.
                "traceback": traceback.format_exc()[-8_000:],
                "validation_stage": (
                    getattr(exc, "stage", None)
                ),
                # Zero-execution stages run before the first official scorer
                # call, so the outer Author interface refunds the (1+2) compile
                # budget for these rejections instead of spending a repair on a
                # spelling/shape error (queue 0004 / 0018).
                "zero_execution_static": (
                    getattr(exc, "stage", None) in _ZERO_EXECUTION_STAGES
                    or not getattr(self, "_official_execution_started", True)
                ),
                "errors": _serializable_exception_errors(exc),
                "draft_revision_sha256": self._draft_revision_sha256,
                "official_runtime_contract": OFFICIAL_RUNTIME_CONTRACT,
                "reviewer_signals": reviewer_signals,
                "builder_contract_findings": builder_contract_findings,
                "distribution_statistics": statistic_only_advisories,
            }
            self.latest_result = result
            self._journal_compile_attempt(result)
            return json.dumps(result, ensure_ascii=False, sort_keys=True)
