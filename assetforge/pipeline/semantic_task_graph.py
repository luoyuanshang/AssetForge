"""Lossless semantic graph for deterministic the benchmark task projections.

The Author owns every semantic node in this graph.  This module only replaces
fragile numeric cross-references with stable symbolic identifiers and derives
the redundant official ``task_source`` projections deterministically.  It does
not invent assertions, counterexamples, state paths, or business requirements.
"""
from __future__ import annotations

import copy
from typing import Any, Iterable, Mapping


SEMANTIC_GRAPH_SCHEMA = "automation-author-semantic-graph-v3"

_TASK_SOURCE_KEYS = (
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
)

_CLASSIFICATION_TO_OBLIGATION_KIND = {
    "required_effect_target": "required_effect",
    "decision_source": "decision_source",
    "protected_non_target": "preservation",
}
_OBLIGATION_KIND_TO_CLASSIFICATION = {
    value: key for key, value in _CLASSIFICATION_TO_OBLIGATION_KIND.items()
}

_SEMANTIC_GRAPH_KEYS = {
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


class SemanticGraphValidationError(ValueError):
    """Bounded same-layer diagnostics for one Author semantic graph."""

    def __init__(self, stage: str, errors: list[dict[str, Any]]) -> None:
        self.stage = stage
        self.errors = copy.deepcopy(errors)
        super().__init__(
            f"{stage} failed with {len(errors)} independent error(s): "
            + "; ".join(str(row.get("message") or "") for row in errors[:24])
        )


def _run_semantic_validation_stage(
    stage: str,
    checks: list[tuple[str, Any]],
) -> None:
    """Report every independent top-level field defect in one Author repair turn."""

    errors: list[dict[str, Any]] = []
    for code, check in checks:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - bounded Author-facing diagnostics
            errors.append(
                {
                    "code": code,
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:4_000],
                }
            )
    if errors:
        raise SemanticGraphValidationError(stage, errors)


def _require_exact_graph_keys(value: Mapping[str, Any]) -> None:
    missing = sorted(_SEMANTIC_GRAPH_KEYS - set(value))
    extra = sorted(set(value) - _SEMANTIC_GRAPH_KEYS)
    if missing or extra:
        raise ValueError(f"semantic_graph keys mismatch: missing={missing}, extra={extra}")


def _require_schema_version(value: Mapping[str, Any]) -> None:
    if value.get("schema_version") != SEMANTIC_GRAPH_SCHEMA:
        raise ValueError(f"unsupported semantic graph schema: {value.get('schema_version')!r}")


def _require_string_list(value: Any, label: str) -> None:
    rows = _require_list(value, label)
    if any(not isinstance(row, str) or not row.strip() for row in rows):
        raise TypeError(f"{label} must contain only non-empty strings")


def _require_nonempty_string(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{label} must be a non-empty string")


def _require_closure_shape(value: Any) -> None:
    closure = _require_mapping(value, "closure")
    _require_list(closure.get("creation_collections"), "closure.creation_collections")
    _require_mapping(closure.get("temporality"), "closure.temporality")


def _validate_requirement_bindings(
    value: Mapping[str, Any],
    assertion_index: Mapping[str, int],
    test_index: Mapping[str, int],
) -> None:
    """Batch every independent requirement/state ownership defect in one diagnostic."""

    errors: list[dict[str, Any]] = []
    requirement_ids: set[str] = set()
    claimed_paths: dict[str, str] = {}
    requirements = _require_list(value.get("requirement_nodes"), "requirement_nodes")
    for index, raw in enumerate(requirements):
        label = f"requirement_nodes[{index}]"
        try:
            row = _require_mapping(raw, label)
        except Exception as exc:  # noqa: BLE001
            errors.append({"code": f"requirement_{index:03d}", "error_type": type(exc).__name__, "message": str(exc)})
            continue
        expected = {
            "id",
            "obligation_kind",
            "requirement",
            "state_bindings",
            "assertion_ids",
            "counterexample_ids",
        }
        if set(row) != expected:
            errors.append(
                {
                    "code": f"requirement_{index:03d}_keys",
                    "error_type": "ValueError",
                    "message": f"{label} must contain exactly one semantic obligation contract",
                }
            )
            continue
        requirement_id = str(row.get("id") or "").strip()
        if not requirement_id or requirement_id in requirement_ids:
            errors.append(
                {
                    "code": f"requirement_{index:03d}_id",
                    "error_type": "ValueError",
                    "message": f"invalid or duplicate requirement id: {requirement_id!r}",
                }
            )
        else:
            requirement_ids.add(requirement_id)
        for key, indices in (
            ("assertion_ids", assertion_index),
            ("counterexample_ids", test_index),
        ):
            try:
                _resolve_ids(row.get(key), indices, f"{label}.{key}")
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    {
                        "code": f"requirement_{index:03d}_{key}",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
        try:
            state_bindings = _require_mapping(row.get("state_bindings"), f"{label}.state_bindings")
        except Exception as exc:  # noqa: BLE001
            errors.append(
                {
                    "code": f"requirement_{index:03d}_state_bindings",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            continue
        classification = _OBLIGATION_KIND_TO_CLASSIFICATION.get(
            str(row.get("obligation_kind") or "")
        )
        for raw_path, public_basis in state_bindings.items():
            state_path = str(raw_path or "").strip()
            if not state_path:
                errors.append(
                    {
                        "code": f"requirement_{index:03d}_empty_state_path",
                        "error_type": "ValueError",
                        "message": f"{label}.state_bindings has an empty state path",
                    }
                )
                continue
            if classification is None and public_basis is not None:
                errors.append(
                    {
                        "code": f"requirement_{index:03d}_ledger_only_binding",
                        "error_type": "ValueError",
                        "message": f"{label}.state_bindings[{state_path!r}] must be null because this obligation kind has no state-surface projection",
                    }
                )
            if classification is not None and (
                not isinstance(public_basis, str) or not public_basis.strip()
            ):
                errors.append(
                    {
                        "code": f"requirement_{index:03d}_public_basis",
                        "error_type": "ValueError",
                        "message": f"{label}.state_bindings[{state_path!r}] must provide a non-empty public basis",
                    }
                )
            if classification is not None and state_path in claimed_paths:
                errors.append(
                    {
                        "code": f"requirement_{index:03d}_duplicate_state_path",
                        "error_type": "ValueError",
                        "message": f"state path {state_path!r} is owned by both {claimed_paths[state_path]} and {requirement_id}",
                    }
                )
            elif classification is not None:
                claimed_paths[state_path] = requirement_id

    out_of_scope = _require_mapping(value.get("out_of_scope_state"), "out_of_scope_state")
    for raw_path, public_basis in out_of_scope.items():
        state_path = str(raw_path or "").strip()
        if not state_path:
            errors.append(
                {"code": "out_of_scope_empty_path", "error_type": "ValueError", "message": "out_of_scope_state has an empty state path"}
            )
            continue
        if state_path in claimed_paths:
            errors.append(
                {
                    "code": "out_of_scope_scored_collision",
                    "error_type": "ValueError",
                    "message": f"state path {state_path!r} cannot be both scored and out_of_scope",
                }
            )
        if not isinstance(public_basis, str) or not public_basis.strip():
            errors.append(
                {
                    "code": "out_of_scope_public_basis",
                    "error_type": "ValueError",
                    "message": f"out_of_scope_state[{state_path!r}] must provide a non-empty public basis",
                }
            )
    if errors:
        raise SemanticGraphValidationError("semantic_graph_bindings", errors)


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return copy.deepcopy(dict(value))


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be a list")
    return copy.deepcopy(value)


def _index_by_id(rows: Iterable[Mapping[str, Any]], label: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    normalized: list[dict[str, Any]] = []
    indices: dict[str, int] = {}
    for index, raw in enumerate(rows):
        row = _require_mapping(raw, f"{label}[{index}]")
        node_id = str(row.pop("id", "") or "").strip()
        if not node_id:
            raise ValueError(f"{label}[{index}].id must be non-empty")
        if node_id in indices:
            raise ValueError(f"duplicate {label} id: {node_id}")
        indices[node_id] = index
        normalized.append(row)
    return normalized, indices


def _payload_nodes(
    rows: Iterable[Mapping[str, Any]],
    *,
    label: str,
    payload_key: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    payloads: list[dict[str, Any]] = []
    indices: dict[str, int] = {}
    for index, raw in enumerate(rows):
        row = _require_mapping(raw, f"{label}[{index}]")
        node_id = str(row.get("id") or "").strip()
        if not node_id or node_id in indices:
            raise ValueError(f"invalid or duplicate {label} id: {node_id!r}")
        indices[node_id] = index
        payloads.append(_require_mapping(row.get(payload_key), f"{label}[{index}].{payload_key}"))
    return payloads, indices


def _resolve_ids(values: Any, indices: Mapping[str, int], label: str) -> list[int]:
    ids = _require_list(values, label)
    resolved: list[int] = []
    for index, value in enumerate(ids):
        node_id = str(value or "").strip()
        if node_id not in indices:
            raise ValueError(f"{label}[{index}] references unknown id: {node_id}")
        resolved.append(indices[node_id])
    if len(set(resolved)) != len(resolved):
        raise ValueError(f"{label} must not contain duplicate ids")
    return resolved


def task_source_to_semantic_graph(source: Mapping[str, Any]) -> dict[str, Any]:
    """Convert one accepted official task source into a symbolic semantic graph.

    The conversion is deliberately strict: every state-surface row must map to
    exactly one obligation carrying the same assertion/counterexample semantics.
    A source that needs two competing truths fails closed instead of acquiring an
    escape hatch in the graph schema.
    """

    value = _require_mapping(source, "task_source")
    assertions = _require_list(value.get("assertions"), "assertions")
    tests = _require_list(
        value.get("scorer_counterexample_tests"),
        "scorer_counterexample_tests",
    )
    ledger = _require_list(value.get("scorer_obligation_ledger"), "scorer_obligation_ledger")
    surface = _require_list(value.get("state_surface_manifest"), "state_surface_manifest")

    assertion_ids = [f"assertion-{index:03d}" for index in range(len(assertions))]
    test_ids = [f"counterexample-{index:03d}" for index in range(len(tests))]
    requirement_ids = [f"requirement-{index:03d}" for index in range(len(ledger))]

    requirements: list[dict[str, Any]] = []
    for index, raw in enumerate(ledger):
        row = _require_mapping(raw, f"scorer_obligation_ledger[{index}]")
        assertion_indices = _require_list(row.pop("assertion_indices", None), "assertion_indices")
        test_indices = _require_list(
            row.pop("counterexample_test_indices", None),
            "counterexample_test_indices",
        )
        try:
            named_assertions = [assertion_ids[int(item)] for item in assertion_indices]
            named_tests = [test_ids[int(item)] for item in test_indices]
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError(f"ledger[{index}] has an invalid numeric reference") from exc
        obligation_kind = str(row.get("obligation_kind") or "")
        classification = _OBLIGATION_KIND_TO_CLASSIFICATION.get(obligation_kind)
        state_paths = _require_list(row.pop("state_paths", None), "state_paths")
        state_bindings: dict[str, Any] = {}
        for state_path in state_paths:
            path = str(state_path or "")
            matches = [
                surface_row
                for surface_row in surface
                if classification is not None
                and surface_row.get("classification") == classification
                and surface_row.get("state_path") == path
                and set(surface_row.get("assertion_indices") or []) == set(assertion_indices)
                and set(surface_row.get("counterexample_test_indices") or []) == set(test_indices)
            ]
            if classification is not None:
                if len(matches) != 1:
                    raise ValueError(
                        "state surface must map to exactly one semantically identical obligation: "
                        f"ledger={index} path={path!r} matches={len(matches)}"
                    )
                state_bindings[path] = matches[0].get("public_basis")
            else:
                # This ledger-only state path has no official state-surface class.
                state_bindings[path] = None
        requirements.append(
            {
                "id": requirement_ids[index],
                **row,
                "state_bindings": state_bindings,
                "assertion_ids": named_assertions,
                "counterexample_ids": named_tests,
            }
        )

    out_of_scope_state: dict[str, Any] = {}
    for index, raw in enumerate(surface):
        row = _require_mapping(raw, f"state_surface_manifest[{index}]")
        state_path = str(row.get("state_path") or "")
        classification = str(row.get("classification") or "")
        assertion_indices = _require_list(row.get("assertion_indices"), "assertion_indices")
        test_indices = _require_list(
            row.get("counterexample_test_indices"),
            "counterexample_test_indices",
        )
        if classification == "out_of_scope":
            if assertion_indices or test_indices:
                raise ValueError(
                    f"state surface row={index} has an invalid out-of-scope contract"
                )
            if state_path in out_of_scope_state:
                raise ValueError(f"duplicate out-of-scope state path: {state_path}")
            out_of_scope_state[state_path] = row.get("public_basis")

    closure = _require_mapping(value.get("contract_closure_manifest"), "contract_closure_manifest")
    creations = _require_list(
        closure.get("creation_collections"),
        "contract_closure_manifest.creation_collections",
    )
    symbolic_creations: list[dict[str, Any]] = []
    for index, raw in enumerate(creations):
        row = _require_mapping(raw, f"creation_collections[{index}]")
        try:
            count_id = assertion_ids[int(row.pop("exact_count_assertion_index"))]
            identity_ids = [
                assertion_ids[int(item)]
                for item in _require_list(
                    row.pop("identity_assertion_indices"),
                    f"creation_collections[{index}].identity_assertion_indices",
                )
            ]
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError(
                f"creation_collections[{index}] has an invalid assertion reference"
            ) from exc
        symbolic_creations.append(
            {
                **row,
                "exact_count_assertion_id": count_id,
                "identity_assertion_ids": identity_ids,
            }
        )
    closure["creation_collections"] = symbolic_creations
    temporality = _require_mapping(closure.get("temporality"), "contract_closure_manifest.temporality")
    history_indices = _require_list(
        temporality.pop("history_assertion_indices", None),
        "history_assertion_indices",
    )
    try:
        temporality["history_assertion_ids"] = [assertion_ids[int(item)] for item in history_indices]
    except (IndexError, TypeError, ValueError) as exc:
        raise ValueError("temporality has an invalid assertion reference") from exc
    closure["temporality"] = temporality

    passthrough = {
        key: copy.deepcopy(value.get(key))
        for key in (
            "task_instruction",
            "initial_state",
            "oracle_actions",
            "forbidden_extra_actions",
            "tool_names",
        )
    }
    return {
        "schema_version": SEMANTIC_GRAPH_SCHEMA,
        **passthrough,
        "assertion_nodes": [
            {"id": assertion_ids[index], "assertion": copy.deepcopy(assertion)}
            for index, assertion in enumerate(assertions)
        ],
        "counterexample_nodes": [
            {"id": test_ids[index], "counterexample": copy.deepcopy(test)}
            for index, test in enumerate(tests)
        ],
        "requirement_nodes": requirements,
        "out_of_scope_state": out_of_scope_state,
        "closure": closure,
    }


def semantic_graph_to_task_source(graph: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministically derive all official task-source projections."""

    value = _require_mapping(graph, "semantic_graph")
    _run_semantic_validation_stage(
        "semantic_graph_structure",
        [
            ("top_level_keys", lambda: _require_exact_graph_keys(value)),
            ("schema_version", lambda: _require_schema_version(value)),
            (
                "task_instruction",
                lambda: _require_nonempty_string(value.get("task_instruction"), "task_instruction"),
            ),
            ("initial_state", lambda: _require_mapping(value.get("initial_state"), "initial_state")),
            ("oracle_actions", lambda: _require_list(value.get("oracle_actions"), "oracle_actions")),
            (
                "forbidden_extra_actions",
                lambda: _require_list(value.get("forbidden_extra_actions"), "forbidden_extra_actions"),
            ),
            ("tool_names", lambda: _require_string_list(value.get("tool_names"), "tool_names")),
            (
                "assertion_nodes",
                lambda: _payload_nodes(
                    _require_list(value.get("assertion_nodes"), "assertion_nodes"),
                    label="assertion_nodes",
                    payload_key="assertion",
                ),
            ),
            (
                "counterexample_nodes",
                lambda: _payload_nodes(
                    _require_list(value.get("counterexample_nodes"), "counterexample_nodes"),
                    label="counterexample_nodes",
                    payload_key="counterexample",
                ),
            ),
            (
                "requirement_nodes",
                lambda: _require_list(value.get("requirement_nodes"), "requirement_nodes"),
            ),
            (
                "out_of_scope_state",
                lambda: _require_mapping(value.get("out_of_scope_state"), "out_of_scope_state"),
            ),
            ("closure", lambda: _require_closure_shape(value.get("closure"))),
        ],
    )

    raw_assertion_nodes = _require_list(value.get("assertion_nodes"), "assertion_nodes")
    assertions, assertion_index = _payload_nodes(
        raw_assertion_nodes,
        label="assertion_nodes",
        payload_key="assertion",
    )
    raw_test_nodes = _require_list(value.get("counterexample_nodes"), "counterexample_nodes")
    tests, test_index = _payload_nodes(
        raw_test_nodes,
        label="counterexample_nodes",
        payload_key="counterexample",
    )

    _validate_requirement_bindings(value, assertion_index, test_index)

    raw_requirements = _require_list(value.get("requirement_nodes"), "requirement_nodes")
    ledger: list[dict[str, Any]] = []
    requirement_ids: set[str] = set()
    surface: list[dict[str, Any]] = []
    claimed_surface_paths: dict[str, str] = {}
    for index, raw in enumerate(raw_requirements):
        row = _require_mapping(raw, f"requirement_nodes[{index}]")
        if set(row) != {
            "id",
            "obligation_kind",
            "requirement",
            "state_bindings",
            "assertion_ids",
            "counterexample_ids",
        }:
            raise ValueError(
                f"requirement_nodes[{index}] must contain exactly one semantic obligation contract"
            )
        requirement_id = str(row.pop("id", "") or "").strip()
        if not requirement_id or requirement_id in requirement_ids:
            raise ValueError(f"invalid or duplicate requirement id: {requirement_id!r}")
        requirement_ids.add(requirement_id)
        assertion_indices = _resolve_ids(
            row.pop("assertion_ids", None),
            assertion_index,
            f"requirement_nodes[{index}].assertion_ids",
        )
        test_indices = _resolve_ids(
            row.pop("counterexample_ids", None),
            test_index,
            f"requirement_nodes[{index}].counterexample_ids",
        )
        state_bindings = _require_mapping(
            row.pop("state_bindings", None),
            f"requirement_nodes[{index}].state_bindings",
        )
        normalized_paths: list[str] = []
        classification = _OBLIGATION_KIND_TO_CLASSIFICATION.get(
            str(row.get("obligation_kind") or "")
        )
        for raw_path, public_basis in state_bindings.items():
            state_path = str(raw_path or "").strip()
            if not state_path:
                raise ValueError(
                    f"requirement_nodes[{index}].state_bindings has an empty state path"
                )
            normalized_paths.append(state_path)
            if classification is None:
                if public_basis is not None:
                    raise ValueError(
                        f"requirement_nodes[{index}].state_bindings[{state_path!r}] must be null "
                        "because this obligation kind has no state-surface projection"
                    )
                continue
            if not isinstance(public_basis, str) or not public_basis.strip():
                raise ValueError(
                    f"requirement_nodes[{index}].state_bindings[{state_path!r}] must provide "
                    "a non-empty public basis"
                )
            if state_path in claimed_surface_paths:
                raise ValueError(
                    f"state path {state_path!r} is owned by both "
                    f"{claimed_surface_paths[state_path]} and {requirement_id}"
                )
            claimed_surface_paths[state_path] = requirement_id
            surface.append(
                {
                    "state_path": state_path,
                    "classification": classification,
                    "public_basis": public_basis,
                    "assertion_indices": copy.deepcopy(assertion_indices),
                    "counterexample_test_indices": copy.deepcopy(test_indices),
                }
            )
        ledger.append({
            **copy.deepcopy(row),
            "state_paths": normalized_paths,
            "assertion_indices": assertion_indices,
            "counterexample_test_indices": test_indices,
        })

    out_of_scope_state = _require_mapping(
        value.get("out_of_scope_state"),
        "out_of_scope_state",
    )
    for raw_path, public_basis in out_of_scope_state.items():
        state_path = str(raw_path or "").strip()
        if not state_path:
            raise ValueError("out_of_scope_state has an empty state path")
        if state_path in claimed_surface_paths:
            raise ValueError(
                f"state path {state_path!r} cannot be both scored and out_of_scope"
            )
        if not isinstance(public_basis, str) or not public_basis.strip():
            raise ValueError(
                f"out_of_scope_state[{state_path!r}] must provide a non-empty public basis"
            )
        surface.append(
            {
                "state_path": state_path,
                "classification": "out_of_scope",
                "public_basis": public_basis,
                "assertion_indices": [],
                "counterexample_test_indices": [],
            }
        )

    closure = _require_mapping(value.get("closure"), "closure")
    creations = _require_list(closure.get("creation_collections"), "closure.creation_collections")
    projected_creations: list[dict[str, Any]] = []
    for index, raw in enumerate(creations):
        row = _require_mapping(raw, f"closure.creation_collections[{index}]")
        count_id = str(row.pop("exact_count_assertion_id", "") or "").strip()
        if count_id not in assertion_index:
            raise ValueError(
                f"closure.creation_collections[{index}] references unknown count assertion: {count_id}"
            )
        identity_indices = _resolve_ids(
            row.pop("identity_assertion_ids", None),
            assertion_index,
            f"closure.creation_collections[{index}].identity_assertion_ids",
        )
        projected_creations.append(
            {
                **row,
                "exact_count_assertion_index": assertion_index[count_id],
                "identity_assertion_indices": identity_indices,
            }
        )
    closure["creation_collections"] = projected_creations
    temporality = _require_mapping(closure.get("temporality"), "closure.temporality")
    temporality["history_assertion_indices"] = _resolve_ids(
        temporality.pop("history_assertion_ids", None),
        assertion_index,
        "closure.temporality.history_assertion_ids",
    )
    closure["temporality"] = temporality

    result = {
        "task_instruction": copy.deepcopy(value.get("task_instruction")),
        "initial_state": copy.deepcopy(value.get("initial_state")),
        "assertions": assertions,
        "oracle_actions": copy.deepcopy(value.get("oracle_actions")),
        "forbidden_extra_actions": copy.deepcopy(value.get("forbidden_extra_actions")),
        "scorer_counterexample_tests": tests,
        "scorer_obligation_ledger": ledger,
        "state_surface_manifest": surface,
        "contract_closure_manifest": closure,
        "tool_names": copy.deepcopy(value.get("tool_names")),
    }
    if set(result) != set(_TASK_SOURCE_KEYS):
        raise AssertionError("deterministic task-source projection changed its key contract")
    return result


def task_source_core(source: Mapping[str, Any]) -> dict[str, Any]:
    """Return only fields accepted at the Author compile-tool boundary."""

    value = _require_mapping(source, "task_source")
    return {key: copy.deepcopy(value.get(key)) for key in _TASK_SOURCE_KEYS}
