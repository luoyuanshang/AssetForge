"""Deduplication, task-family splitting and diversity gates for agent corpora.

This module performs only deterministic, repeatable work: mechanical fingerprints, source binding, and validation of reviewer decisions. Whether two tasks are semantically
equivalent must come from a whole-task agent reviewer; code cannot substitute an embedding threshold for a semantic judgement.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from difflib import SequenceMatcher
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable
from uuid import uuid4


REVIEW_SCHEMA = "automation-agent-semantic-family-review-v1"
AUDIT_SCHEMA = "automation-agent-dataset-gates-v1"
GROUPED_SPLIT_SCHEMA = "automation-family-grouped-split-v1"
ALLOWED_DECISIONS = frozenset({"clone", "same_family", "distinct"})
STAGES = frozenset({"single", "pilot10", "reference", "corpus_checkpoint"})
ROOT = Path(__file__).resolve().parents[2]
WORD = re.compile(r"[\u3400-\u9fff]|[a-z]+|\d+", re.IGNORECASE)
LEXICAL_FIVE_GRAM_WARNING = 0.12
LEXICAL_SEQUENCE_WARNING = 0.55


def _tool_list(info):
    """Declared tool list of an external row, under any accepted key."""
    if not isinstance(info, dict):
        return []
    for key in ("tool_names", "tools", "zapier_tools", "api_tools"):
        value = info.get(key)
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value if isinstance(v, str)]
    return []


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _counter_rows(values: Iterable[object]) -> list[list[object]]:
    counts = Counter(str(value) for value in values)
    return [[key, counts[key]] for key in sorted(counts)]


def _normalized_tokens(text: str) -> tuple[str, ...]:
    return tuple("<number>" if token.isdigit() else token.lower() for token in WORD.findall(text))


def _surface_template(text: str) -> str:
    """Collapse numeric literals only, as a warning that a value was swapped; this does not claim to have performed semantic deduplication."""
    return " ".join(_normalized_tokens(text))


def _ngram_jaccard(left: tuple[str, ...], right: tuple[str, ...], width: int = 5) -> float:
    def grams(tokens: tuple[str, ...]) -> set[tuple[str, ...]]:
        if len(tokens) < width:
            return {tokens} if tokens else set()
        return {tokens[index:index + width] for index in range(len(tokens) - width + 1)}

    left_grams, right_grams = grams(left), grams(right)
    union = left_grams | right_grams
    return len(left_grams & right_grams) / len(union) if union else 0.0


def _sequence_ratio(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    return SequenceMatcher(a=left, b=right, autojunk=False).ratio()


def _assertion_dependency_shape(task: dict[str, Any]) -> list[list[object]]:
    info = task.get("info") if isinstance(task.get("info"), dict) else {}
    assertions = task.get("assertions") or info.get("assertions") or []
    by_id = {
        str(row.get("id")): str(row.get("type") or "unknown")
        for row in assertions
        if isinstance(row, dict) and row.get("id") is not None
    }
    pairs: list[str] = []
    for edge in (
        task.get("assertion_dependency_edges")
        or info.get("assertion_dependency_edges")
        or []
    ):
        if not isinstance(edge, list) or len(edge) != 2:
            continue
        pairs.append(f"{by_id.get(str(edge[0]), 'unknown')}->{by_id.get(str(edge[1]), 'unknown')}")
    return _counter_rows(pairs)


def mechanical_program_descriptor(task: dict[str, Any]) -> dict[str, Any]:
    """Build an entity/value-stripped mechanical program description. A collision only triggers review; it never directly declares a semantic clone."""
    #  the benchmark scorer/runtime  ``info`` ；
    # author packages use top-level fields. Both layouts must yield a real description -- silently projecting a task to an "empty program" makes the set reviewer merge
    # families wrongly, with no task semantics to work from.
    info = task.get("info") if isinstance(task.get("info"), dict) else {}
    catalog_value = (task.get("api_catalog") or info.get("api_catalog")
                     or _tool_list(info) or [])
    catalog = [row for row in catalog_value if isinstance(row, dict)]
    assertion_value = task.get("assertions") or info.get("assertions") or []
    assertions = [row for row in assertion_value if isinstance(row, dict)]
    runtime_value = task.get("runtime_config") or info.get("runtime_config") or {}
    runtime = runtime_value if isinstance(runtime_value, dict) else {}
    initial_state = info.get("initial_state") if isinstance(info.get("initial_state"), dict) else {}
    allowed_apps = task.get("allowed_apps") or info.get("allowed_apps") or sorted(initial_state)
    app_capabilities = task.get("app_capabilities") or info.get("app_capabilities") or {}
    capability_shapes = sorted(
        tuple(sorted(str(item) for item in values))
        for values in app_capabilities.values()
        if isinstance(values, list)
    )
    collections_per_app: dict[str, set[str]] = defaultdict(set)
    for row in catalog:
        collections_per_app[str(row.get("app") or "unknown")].add(str(row.get("collection") or "unknown"))
    return {
        "app_count": len(allowed_apps),
        "collection_counts_per_app": sorted(len(values) for values in collections_per_app.values()),
        "capability_shapes": capability_shapes,
        "api_method_operation_counts": _counter_rows(
            f"{row.get('method')}:{row.get('operation')}" for row in catalog
        ),
        "api_parameter_arity": sorted(len(row.get("params_fields") or []) for row in catalog),
        "assertion_type_counts": _counter_rows(row.get("type") or "unknown" for row in assertions),
        "assertion_dependency_type_edges": _assertion_dependency_shape(task),
        "effect_order_constraint_count": len(runtime.get("effect_order_constraints") or []),
        "foreign_key_rule_count": sum(
            len(collections) if isinstance(collections, dict) else 0
            for collections in (runtime.get("foreign_keys") or {}).values()
        ),
        "create_collection_count": sum(
            len(collections) if isinstance(collections, dict) else 0
            for collections in (runtime.get("required_create_fields") or {}).values()
        ),
    }


def public_instruction(task: dict[str, Any]) -> str:
    """Read the single public user instruction of an official task package."""
    instruction = task.get("instruction")
    if isinstance(instruction, str) and instruction.strip():
        return instruction
    prompt = task.get("prompt")
    if isinstance(prompt, list):
        user_messages = [
            str(message.get("content") or "")
            for message in prompt
            if isinstance(message, dict) and message.get("role") == "user"
        ]
        if len(user_messages) == 1 and user_messages[0].strip():
            return user_messages[0]
    return ""


# Legacy module-level names are kept so historical callers keep working; new code should use the public helpers.
_public_instruction = public_instruction


def task_fingerprint(task: dict[str, Any]) -> dict[str, Any]:
    task_id = str(task.get("task_id") or "")
    if not task_id:
        raise ValueError("every task must have task_id")
    instruction = public_instruction(task)
    if not instruction.strip():
        raise ValueError(f"task {task_id} has no instruction")
    descriptor = mechanical_program_descriptor(task)
    return {
        "task_id": task_id,
        "split": str(task.get("split") or "unassigned"),
        "domain": str(task.get("domain_label") or "unassigned"),
        "instruction_sha256": _sha256_bytes(instruction.encode()),
        "surface_template_sha256": _sha256_bytes(_surface_template(instruction).encode()),
        "mechanical_program_signature": _sha256_bytes(_canonical(descriptor).encode()),
        "mechanical_program_descriptor": descriptor,
        "_normalized_tokens": _normalized_tokens(instruction),
    }


def _pair(left: str, right: str) -> tuple[str, str]:
    if left == right:
        raise ValueError("semantic review pair must contain distinct tasks")
    return tuple(sorted((left, right)))


def mechanical_shortlist(fingerprints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reasons: dict[tuple[str, str], set[str]] = defaultdict(set)
    metrics: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    keys = (
        ("instruction_sha256", "exact_instruction"),
        ("surface_template_sha256", "number_only_surface_variant"),
        ("mechanical_program_signature", "same_mechanical_program_shape"),
    )
    for key, reason in keys:
        groups: dict[str, list[str]] = defaultdict(list)
        for row in fingerprints:
            groups[str(row[key])].append(str(row["task_id"]))
        for members in groups.values():
            for index, left in enumerate(sorted(members)):
                for right in sorted(members)[index + 1:]:
                    reasons[_pair(left, right)].add(reason)
    for index, left in enumerate(fingerprints):
        for right in fingerprints[index + 1:]:
            pair = _pair(str(left["task_id"]), str(right["task_id"]))
            left_tokens = tuple(left["_normalized_tokens"])
            right_tokens = tuple(right["_normalized_tokens"])
            jaccard = _ngram_jaccard(left_tokens, right_tokens)
            ratio = _sequence_ratio(left_tokens, right_tokens)
            metrics[pair] = {
                "normalized_5gram_jaccard": round(jaccard, 6),
                "normalized_token_sequence_ratio": round(ratio, 6),
            }
            if jaccard >= LEXICAL_FIVE_GRAM_WARNING:
                reasons[pair].add("normalized_5gram_jaccard_warning")
            if ratio >= LEXICAL_SEQUENCE_WARNING:
                reasons[pair].add("normalized_token_sequence_ratio_warning")
    return [
        {
            "left_task_id": pair[0],
            "right_task_id": pair[1],
            "reasons": sorted(values),
            "metrics": metrics.get(pair, {}),
        }
        for pair, values in sorted(reasons.items())
    ]


def _load_review(path: Path | None, task_ids: set[str], shortlist: list[dict[str, Any]]) -> dict[str, Any]:
    if path is None:
        return {
            "provided": False,
            "valid": False,
            "assignments": {},
            "decisions": {},
            "errors": ["semantic_review_not_provided"],
        }
    value = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if value.get("schema_version") != REVIEW_SCHEMA:
        errors.append("wrong_review_schema")
    if value.get("reviewer_alias") != "capture_model_2_sol_extra_high":
        errors.append("wrong_reviewer_alias")
    memo = Path(str(value.get("memo_path") or ""))
    if not memo.is_absolute():
        memo = path.parent / memo
    if not memo.is_file() or _sha256_path(memo) != value.get("memo_sha256"):
        errors.append("review_memo_hash_mismatch")
    assignments: dict[str, str] = {}
    for row in value.get("assignments") or []:
        if not isinstance(row, dict):
            errors.append("invalid_assignment_row")
            continue
        task_id = str(row.get("task_id") or "")
        family_id = str(row.get("semantic_family_id") or "")
        if task_id in assignments or task_id not in task_ids or not family_id:
            errors.append("invalid_or_duplicate_assignment")
        else:
            assignments[task_id] = family_id
    if set(assignments) != task_ids:
        errors.append("assignments_do_not_cover_all_tasks")
    decisions: dict[tuple[str, str], str] = {}
    for row in value.get("pair_decisions") or []:
        if not isinstance(row, dict):
            errors.append("invalid_pair_decision_row")
            continue
        try:
            pair = _pair(str(row.get("left_task_id") or ""), str(row.get("right_task_id") or ""))
        except ValueError:
            errors.append("invalid_pair_identity")
            continue
        decision = str(row.get("decision") or "")
        if pair in decisions or not set(pair) <= task_ids or decision not in ALLOWED_DECISIONS:
            errors.append("invalid_or_duplicate_pair_decision")
        else:
            decisions[pair] = decision
    required_pairs = {
        _pair(str(row["left_task_id"]), str(row["right_task_id"])) for row in shortlist
    }
    if not required_pairs <= set(decisions):
        errors.append("mechanical_shortlist_not_fully_reviewed")
    for pair, decision in decisions.items():
        same = assignments.get(pair[0]) == assignments.get(pair[1])
        if decision in {"clone", "same_family"} and not same:
            errors.append("same_family_decision_assignment_mismatch")
        if decision == "distinct" and same:
            errors.append("distinct_decision_assignment_mismatch")
    return {
        "provided": True,
        "valid": not errors,
        "assignments": assignments,
        "decisions": decisions,
        "errors": sorted(set(errors)),
        "path": str(path),
        "sha256": _sha256_path(path),
        "memo_path": str(memo),
    }


def build_grouped_split_manifest(
    *,
    tasks: list[dict[str, Any]],
    semantic_review_path: Path,
    eval_fraction: float = 0.0,
    seed: str = "automation-pilot-family-split-v1",
) -> dict[str, Any]:
    """Group by complete semantic task family and deterministically derive a train/eval split.

    The compiled task is not modified; the manifest is a source-bound grouping policy over the training-corpus view.
    """
    if not 0.0 <= eval_fraction < 1.0:
        raise ValueError("eval fraction must be within [0, 1)")
    fingerprints = [task_fingerprint(task) for task in tasks]
    task_ids = {str(row["task_id"]) for row in fingerprints}
    shortlist = mechanical_shortlist(fingerprints)
    review = _load_review(semantic_review_path, task_ids, shortlist)
    if not review["valid"]:
        raise ValueError(
            "cannot group-split an invalid semantic review: "
            + ",".join(review["errors"])
        )
    if any(decision == "clone" for decision in review["decisions"].values()):
        raise ValueError("cannot group-split a corpus containing semantic clones")
    family_members: dict[str, list[str]] = defaultdict(list)
    for task_id, family_id in review["assignments"].items():
        family_members[family_id].append(task_id)
    if len(family_members) < 2:
        raise ValueError("grouped split requires at least two semantic families")
    ordered_families = sorted(
        family_members,
        key=lambda family_id: _sha256_bytes(f"{seed}\0{family_id}".encode()),
    )
    target_eval = round(len(tasks) * eval_fraction)
    eval_families: set[str] = set()
    eval_count = 0
    for family_id in ordered_families:
        if eval_count >= target_eval:
            break
        eval_families.add(family_id)
        eval_count += len(family_members[family_id])
    if len(eval_families) == len(family_members):
        eval_families.remove(ordered_families[-1])
    by_task = {str(row["task_id"]): row for row in fingerprints}
    rows = []
    for task_id in sorted(task_ids):
        family_id = review["assignments"][task_id]
        rows.append({
            "task_id": task_id,
            "task_content_sha256": _sha256_bytes(
                _canonical(next(task for task in tasks if str(task.get("task_id")) == task_id)).encode()
            ),
            "semantic_family_id": family_id,
            "domain": by_task[task_id]["domain"],
            "split": "eval" if family_id in eval_families else "train",
        })
    value = {
        "schema_version": GROUPED_SPLIT_SCHEMA,
        "policy": {
            "name": "family_grouped_deterministic_hash_v1",
            "seed": seed,
            "requested_eval_fraction": eval_fraction,
            "target_eval_task_count": target_eval,
            "same_family_cross_split_allowed": False,
        },
        "semantic_review": {
            "path": str(semantic_review_path),
            "sha256": _sha256_path(semantic_review_path),
        },
        "task_corpus_sha256": _sha256_bytes((_canonical(tasks) + "\n").encode()),
        "assignments": rows,
        "split_counts": dict(sorted(Counter(row["split"] for row in rows).items())),
        "family_counts": dict(sorted(Counter(review["assignments"].values()).items())),
    }
    value["content_sha256"] = _sha256_bytes(_canonical(value).encode())
    return value


def _load_grouped_split(
    path: Path | None,
    *,
    tasks: list[dict[str, Any]],
    semantic_review_path: Path | None,
) -> dict[str, Any]:
    if path is None:
        return {"provided": False, "valid": True, "assignments": {}, "errors": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if value.get("schema_version") != GROUPED_SPLIT_SCHEMA:
        errors.append("wrong_grouped_split_schema")
    review = value.get("semantic_review") if isinstance(value.get("semantic_review"), dict) else {}
    if semantic_review_path is None or review.get("sha256") != _sha256_path(semantic_review_path):
        errors.append("grouped_split_semantic_review_hash_mismatch")
    expected_corpus = _sha256_bytes((_canonical(tasks) + "\n").encode())
    if value.get("task_corpus_sha256") != expected_corpus:
        errors.append("grouped_split_task_corpus_hash_mismatch")
    expected_tasks = {str(task.get("task_id") or ""): task for task in tasks}
    assignments: dict[str, dict[str, str]] = {}
    for row in value.get("assignments") or []:
        if not isinstance(row, dict):
            errors.append("invalid_grouped_split_row")
            continue
        task_id = str(row.get("task_id") or "")
        split = str(row.get("split") or "")
        family_id = str(row.get("semantic_family_id") or "")
        task = expected_tasks.get(task_id)
        expected_sha = (
            _sha256_bytes(_canonical(task).encode()) if task is not None else ""
        )
        if (
            task is None
            or task_id in assignments
            or split not in {"train", "eval"}
            or not family_id
            or row.get("task_content_sha256") != expected_sha
        ):
            errors.append("invalid_or_unbound_grouped_split_assignment")
            continue
        assignments[task_id] = {"split": split, "semantic_family_id": family_id}
    if set(assignments) != set(expected_tasks):
        errors.append("grouped_split_does_not_cover_all_tasks")
    return {
        "provided": True,
        "valid": not errors,
        "assignments": assignments,
        "errors": sorted(set(errors)),
        "path": str(path),
        "sha256": _sha256_path(path),
        "split_counts": value.get("split_counts") or {},
        "policy": value.get("policy") or {},
    }


def _diversity(stage: str, fingerprints: list[dict[str, Any]], assignments: dict[str, str]) -> dict[str, Any]:
    family_counts = Counter(assignments.values())
    domain_counts = Counter(str(row["domain"]) for row in fingerprints)
    task_count = len(fingerprints)
    if stage == "single":
        requirements = {"task_count": 1}
        checks = {"single_task_scope": task_count == 1}
        applicable = False
    elif stage == "pilot10":
        requirements = {
            "task_count": 10,
            "minimum_semantic_families": 6,
            "maximum_tasks_per_family": 2,
            "minimum_domains": 4,
            "maximum_tasks_per_domain": 4,
        }
        checks = {
            "exact_task_count": task_count == 10,
            "minimum_semantic_families": len(family_counts) >= 6,
            "maximum_tasks_per_family": max(family_counts.values(), default=0) <= 2,
            "minimum_domains": len(domain_counts) >= 4,
            "maximum_tasks_per_domain": max(domain_counts.values(), default=0) <= 4,
        }
        applicable = True
    elif stage == "reference":
        requirements = {
            "task_count": 100,
            "minimum_semantic_families": 30,
            "maximum_tasks_per_family": 5,
            "required_domains": 6,
            "minimum_tasks_per_domain": 10,
            "maximum_tasks_per_domain": 25,
        }
        checks = {
            "exact_task_count": task_count == 100,
            "minimum_semantic_families": len(family_counts) >= 30,
            "maximum_tasks_per_family": max(family_counts.values(), default=0) <= 5,
            "required_domains": len(domain_counts) == 6,
            "minimum_tasks_per_domain": min(domain_counts.values(), default=0) >= 10,
            "maximum_tasks_per_domain": max(domain_counts.values(), default=0) <= 25,
        }
        applicable = True
    else:
        # 100  checkpoint  reference
        # ， 150/3000 。
        requirements = {
            "minimum_task_count": 100,
            "corpus100_reference_minimum_semantic_families": 30,
            "corpus100_reference_maximum_tasks_per_family": 5,
            "corpus100_reference_required_domains": 6,
        }
        checks = {
            "minimum_task_count": task_count >= 100,
        }
        applicable = False
    return {
        "applicable": applicable,
        "requirements": requirements,
        "family_counts": dict(sorted(family_counts.items())),
        "domain_counts": dict(sorted(domain_counts.items())),
        "checks": checks,
        "passed": all(checks.values()),
    }


def audit(
    *,
    tasks: list[dict[str, Any]],
    stage: str,
    semantic_review_path: Path | None = None,
    grouped_split_path: Path | None = None,
) -> dict[str, Any]:
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    fingerprints = [task_fingerprint(task) for task in tasks]
    task_ids = [str(row["task_id"]) for row in fingerprints]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("task IDs must be unique")
    shortlist = mechanical_shortlist(fingerprints)
    review = _load_review(semantic_review_path, set(task_ids), shortlist)
    grouped_split = _load_grouped_split(
        grouped_split_path,
        tasks=tasks,
        semantic_review_path=semantic_review_path,
    )
    for row in fingerprints:
        override = grouped_split["assignments"].get(str(row["task_id"]))
        if override is not None:
            row["split"] = override["split"]
    clone_pairs = [list(pair) for pair, decision in sorted(review["decisions"].items()) if decision == "clone"]
    families_to_splits: dict[str, set[str]] = defaultdict(set)
    by_id = {str(row["task_id"]): row for row in fingerprints}
    for task_id, family_id in review["assignments"].items():
        families_to_splits[family_id].add(str(by_id[task_id]["split"]))
    cross_split_families = {
        family: sorted(splits) for family, splits in sorted(families_to_splits.items()) if len(splits) > 1
    }
    diversity = _diversity(stage, fingerprints, review["assignments"])
    semantic_gate_applicable = stage != "single"
    promotion_gate_applicable = stage in {"pilot10", "reference"}
    checks = {
        "semantic_review_valid": review["valid"] if semantic_gate_applicable else True,
        "zero_semantic_clone_pairs": not clone_pairs if semantic_gate_applicable else True,
        "semantic_families_do_not_cross_splits": not cross_split_families if semantic_gate_applicable else True,
        "diversity_quota_passed": diversity["passed"],
        "grouped_split_manifest_valid": grouped_split["valid"],
    }
    result = {
        "schema_version": AUDIT_SCHEMA,
        "stage": stage,
        "task_count": len(tasks),
        "task_corpus_sha256": _sha256_bytes((_canonical(tasks) + "\n").encode()),
        "mechanical_fingerprints": [
            {
                key: value
                for key, value in row.items()
                if key not in {"mechanical_program_descriptor", "_normalized_tokens"}
            }
            for row in fingerprints
        ],
        "mechanical_shortlist": shortlist,
        "mechanical_shortlist_pair_count": len(shortlist),
        "semantic_review": {
            key: value for key, value in review.items() if key not in {"decisions", "assignments"}
        },
        "semantic_clone_pairs": clone_pairs,
        "cross_split_semantic_families": cross_split_families,
        "grouped_split": {
            key: value for key, value in grouped_split.items() if key != "assignments"
        },
        "diversity": diversity,
        "checks": checks,
        "promotion_gate_applicable": promotion_gate_applicable,
        "promotion_gate_passed": promotion_gate_applicable and all(checks.values()),
        "same_native_tools_are_not_a_rejection_signal": True,
        "generic_search_decide_write_readback_is_not_a_rejection_signal": True,
        "embedding_score_used_as_hard_semantic_threshold": False,
        "lexical_warning_thresholds": {
            "normalized_5gram_jaccard_gte": LEXICAL_FIVE_GRAM_WARNING,
            "normalized_token_sequence_ratio_gte": LEXICAL_SEQUENCE_WARNING,
            "effect": "shortlist_for_whole_task_agent_review_only",
        },
        "claim_boundary": (
            "Mechanical signatures only shortlist pairs. Clone/same-family/distinct decisions come from "
            "the source-bound whole-task reviewer memo; tool reuse is intentionally allowed."
        ),
    }
    result["content_sha256"] = _sha256_bytes(_canonical(result).encode())
    return result


def _load_tasks(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".jsonl":
            values = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            value = json.loads(text)
            values = value if isinstance(value, list) else [value]
        if not all(isinstance(value, dict) for value in values):
            raise ValueError(f"task input must contain objects: {path}")
        rows.extend(values)
    return rows


def _project_path(path: Path, *, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must be inside project root: {resolved}") from exc
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, action="append", required=True)
    parser.add_argument("--stage", choices=sorted(STAGES), required=True)
    parser.add_argument("--semantic-review", type=Path)
    parser.add_argument(
        "--write-grouped-split-manifest",
        type=Path,
        help="Write a source-bound family-assignment manifest; defaults to all-train.",
    )
    parser.add_argument(
        "--eval-fraction",
        type=float,
        default=0.0,
        help="Set non-zero only once an eval count/ratio has been explicitly approved.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    task_paths = [_project_path(path, label="task input") for path in args.tasks]
    semantic_review_path = (
        _project_path(args.semantic_review, label="semantic review") if args.semantic_review else None
    )
    tasks = _load_tasks(task_paths)
    grouped_split_path = None
    if args.write_grouped_split_manifest:
        if semantic_review_path is None:
            raise ValueError("grouped split requires --semantic-review")
        grouped_split_path = _project_path(
            args.write_grouped_split_manifest,
            label="grouped split manifest",
        )
        if grouped_split_path.exists():
            raise FileExistsError(f"refusing to overwrite: {grouped_split_path}")
        split_value = build_grouped_split_manifest(
            tasks=tasks,
            semantic_review_path=semantic_review_path,
            eval_fraction=args.eval_fraction,
        )
        grouped_split_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_split = grouped_split_path.with_name(
            f".{grouped_split_path.name}.{uuid4().hex}.tmp"
        )
        try:
            with temporary_split.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(split_value, ensure_ascii=False, indent=2) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_split, grouped_split_path)
        finally:
            temporary_split.unlink(missing_ok=True)
    result = audit(
        tasks=tasks,
        stage=args.stage,
        semantic_review_path=semantic_review_path,
        grouped_split_path=grouped_split_path,
    )
    result["task_sources"] = [
        {"path": str(path.relative_to(ROOT)), "sha256": _sha256_path(path)} for path in task_paths
    ]
    result["content_sha256"] = _sha256_bytes(
        _canonical({key: value for key, value in result.items() if key != "content_sha256"}).encode()
    )
    output = _project_path(args.output, label="output")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({
        "task_count": result["task_count"],
        "stage": result["stage"],
        "promotion_gate_applicable": result["promotion_gate_applicable"],
        "promotion_gate_passed": result["promotion_gate_passed"],
        "content_sha256": result["content_sha256"],
    }, ensure_ascii=False))
    return 0 if (
        result["promotion_gate_passed"]
        or args.stage in {"single", "corpus_checkpoint"}
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
