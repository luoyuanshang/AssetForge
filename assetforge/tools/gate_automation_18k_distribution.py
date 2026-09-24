#!/usr/bin/env python3
"""Fail-closed aggregate gate for the controller-private Automation 18k plan."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "agent_data_factory" / "artifacts" / "controller_assignments" / "automation_18k_distribution_contract.json"
DEFAULT_QUALITY_HOLDS = ROOT / "assetforge/artifacts/qa_quality_holds/automation_qa18k_unresolved.json"


def unresolved_quality_holds(tasks: list[dict[str, Any]]) -> list[str]:
    """Keep independent accepts intact, but never release a known unresolved conflict.

    The ledger and source-bound replay are controller-private, not Author inputs.
    Removing a hold requires an independently recorded resolution, not editing a QA.
    Missing/malformed ledgers or changed evidence fail closed.
    """
    ledger = json.loads(DEFAULT_QUALITY_HOLDS.read_text(encoding="utf-8"))
    if ledger.get("schema_version") != "qa18k-unresolved-quality-holds-v1" or not isinstance(ledger.get("holds"), list):
        raise ValueError("invalid QA quality hold ledger")
    ids = set()
    for row in ledger["holds"]:
        task_id = row.get("task_id")
        if not isinstance(task_id, str) or not task_id or task_id in ids or row.get("status") != "unresolved":
            raise ValueError("invalid/duplicate/unresolved-status QA hold")
        path = (ROOT / row["evidence"]).resolve()
        path.relative_to((ROOT / "agent_data_factory").resolve())
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != row.get("evidence_sha256"):
            raise ValueError("QA hold evidence hash drift")
        evidence = json.loads(payload)
        if evidence.get("task_id") != task_id or evidence.get("task_sha256") != row.get("task_sha256"):
            raise ValueError("QA hold evidence identity drift")
        ids.add(task_id)
    return sorted({str(task["task_id"]) for task in tasks if task.get("task_id") in ids})


def rows(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            task = (value.get("metadata") or {}).get("task") if isinstance(value, dict) else None
            task = task if isinstance(task, dict) else value
            if not isinstance(task, dict):
                raise ValueError(f"row {line_number} is not a task object")
            info = task.get("info")
            if isinstance(info, str):
                task = dict(task)
                task["info"] = json.loads(info)
            yield task


def assertion_type(value: Any) -> str:
    if not isinstance(value, dict):
        return "unknown"
    return str(value.get("type") or value.get("assertion_type") or "unknown")


def scorer_apps(task: dict[str, Any]) -> tuple[str, ...]:
    assertions = list((task.get("info") or {}).get("assertions") or [])
    # Assertion names are ``<service>_<assertion>`` but several official service
    # identifiers themselves contain underscores (for example google_sheets,
    # google_calendar and zoho_desk).  Splitting on the first underscore silently
    # merges distinct applications and corrupts cardinality/combination quotas.
    # The source-bound initial state is the per-task service namespace, so match
    # the longest exact service prefix, mirroring the pinned runtime's service
    # derivation rule.  An unmatched name remains fail-visible instead of being
    # guessed from a truncated prefix.
    service_fields = sorted(initial_apps(task), key=len, reverse=True)
    result: set[str] = set()
    for assertion in assertions:
        name = assertion_type(assertion)
        service = next(
            (
                field
                for field in service_fields
                if name == field or name.startswith(field + "_")
            ),
            None,
        )
        if service is None:
            raise ValueError(
                f"assertion type {name!r} does not bind an initial-state service"
            )
        result.add(service)
    return tuple(sorted(result))


def initial_apps(task: dict[str, Any]) -> tuple[str, ...]:
    state = (task.get("info") or {}).get("initial_state") or {}
    return tuple(sorted(str(value) for value in state if value != "meta"))


def prompt_chars(task: dict[str, Any]) -> int:
    prompt = task.get("prompt") or []
    if isinstance(prompt, str):
        return len(prompt)
    return len("\n".join(
        str(value.get("content") or "")
        for value in prompt
        if isinstance(value, dict) and value.get("role") == "user"
    ))


def percentile(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)] if ordered else 0


def cap(fraction: float, size: int) -> int:
    return max(3, math.ceil(fraction * size))


def union_coverage(tasks: list[dict[str, Any]], contract: dict[str, Any]) -> dict[str, Any]:
    """Count QA containing a member, not the sum of app memberships.

    The archived v3 controller contract used help_scout for native helpscout.
    Normalize only this known contract label; never rename a task or assertion.
    Keep the alias visible in the audit instead of editing an immutable contract.
    """
    aliases = {"help_scout": "helpscout"}
    result = {}
    for name, value in contract.get("undercovered_initial_state_union_minimum", {}).items():
        names = set(value["apps"])
        canonical = {aliases.get(app, app) for app in names}
        result[name] = {
            "unique_qa_count": sum(bool(set(initial_apps(task)) & canonical) for task in tasks),
            "minimum": value["minimum"],
            "canonical_apps": sorted(canonical),
            "contract_label_aliases": {app: aliases[app] for app in sorted(names & aliases.keys())},
        }
    return result


def audit(
    tasks: list[dict[str, Any]],
    contract: dict[str, Any],
    mode: str,
    *,
    baseline_combinations: set[str] | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    root_ids = [((task.get('generation_provenance') or {}).get('qa_repair_lineage') or {}).get(
        'root_task_id', task.get('task_id')) for task in tasks]
    duplicated_roots = sorted(str(k) for k,v in Counter(root_ids).items() if k and v>1)
    failures.extend(f'multiple accepted revisions of the same root QA: {key}' for key in duplicated_roots)
    held_task_ids = unresolved_quality_holds(tasks)
    failures.extend(f"unresolved quality hold: {task_id}" for task_id in held_task_ids)
    domain_counts = Counter(str(task.get("domain_label") or "") for task in tasks)
    cardinality = Counter(str(len(scorer_apps(task))) for task in tasks)
    combinations = Counter("+".join(scorer_apps(task)) for task in tasks)
    novel_combination_count = (
        sum(
            "+".join(scorer_apps(task)) not in baseline_combinations
            for task in tasks
        )
        if baseline_combinations is not None
        else None
    )
    initial_membership: Counter[str] = Counter()
    for task in tasks:
        initial_membership.update(initial_apps(task))
    unions = union_coverage(tasks, contract)
    prompt_lengths = [prompt_chars(task) for task in tasks]
    assertion_counts = [len(list((task.get("info") or {}).get("assertions") or [])) for task in tasks]

    for domain, target in contract["domain_targets"].items():
        observed = domain_counts[domain]
        if observed > target["total"]:
            failures.append(f"{domain}: {observed} exceeds target {target['total']}")
        if mode == "terminal" and observed != target["total"]:
            failures.append(f"{domain}: terminal count {observed} != {target['total']}")
        domain_tasks = [task for task in tasks if task.get("domain_label") == domain]
        if len(domain_tasks) >= 100:
            counts = [len(list((task.get("info") or {}).get("assertions") or [])) for task in domain_tasks]
            low, high = contract["assertion_median_by_domain"][domain]
            observed_median = median(counts)
            if not low <= observed_median <= high:
                failures.append(f"{domain}: assertion median {observed_median} outside [{low}, {high}]")
            domain_cardinality = Counter(str(len(scorer_apps(task))) for task in domain_tasks)
            tolerance = float(contract["live_cardinality_fraction_tolerance"])
            for key, target_count in target["scorer_app_cardinality"].items():
                target_fraction = target_count / target["total"]
                upper = math.ceil((target_fraction + tolerance) * len(domain_tasks))
                if domain_cardinality[key] > upper:
                    failures.append(f"{domain}: app cardinality {key} overshoot {domain_cardinality[key]} > {upper}")
        if mode == "terminal":
            domain_cardinality = Counter(str(len(scorer_apps(task))) for task in domain_tasks)
            if dict(domain_cardinality) != target["scorer_app_cardinality"]:
                failures.append(f"{domain}: terminal scorer app cardinality mismatch")

    if tasks:
        limits = contract["prompt_user_chars"]
        observed_median = median(prompt_lengths)
        if not limits["median_min"] <= observed_median <= limits["median_max"]:
            failures.append(f"prompt median {observed_median} outside target band")
        if percentile(prompt_lengths, 0.75) > limits["p75_max"]:
            failures.append("prompt p75 exceeds target")
        if max(prompt_lengths) > limits["per_item_max"]:
            failures.append("prompt per-item maximum exceeded")
        if max(assertion_counts) > contract["assertion_per_item_max"]:
            failures.append("assertion per-item maximum exceeded")

        caps = contract["concentration_caps"]
        for combination, count in combinations.items():
            fraction = caps["any_scorer_app_combination_fraction"]
            if len(combination.split("+")) == 2:
                fraction = min(fraction, caps["any_two_app_combination_fraction"])
            fraction = caps["specific_combination_fraction"].get(combination, fraction)
            if count > cap(float(fraction), len(tasks)):
                failures.append(f"combination {combination}: {count} exceeds live cap")
        for app, fraction in caps["initial_state_app_membership_fraction"].items():
            if initial_membership[app] > cap(float(fraction), len(tasks)):
                failures.append(f"initial-state app {app}: membership cap exceeded")
        if baseline_combinations is not None and len(tasks) >= 100:
            minimum = float(
                contract["novelty_against_old_pool"]
                ["scorer_app_combination_absent_fraction_min"]
            )
            observed = novel_combination_count / len(tasks)
            if observed < minimum:
                failures.append(
                    f"old-pool-absent scorer app combination fraction "
                    f"{observed:.6f} < {minimum:.6f}"
                )

    if mode == "terminal":
        if dict(cardinality) != contract["global_scorer_app_cardinality"]:
            failures.append("terminal global scorer app cardinality mismatch")
        minimums = contract["undercovered_initial_state_app_minimum"]
        for app, minimum in minimums.items():
            if initial_membership[app] < minimum:
                failures.append(f"initial-state app {app}: terminal minimum not met")
        for name, union in contract["undercovered_initial_state_union_minimum"].items():
            observed = unions[name]["unique_qa_count"]
            if observed < union["minimum"]:
                failures.append(f"{name} union: terminal minimum not met")

    return {
        "schema_version": "automation-18k-distribution-gate-receipt-v1",
        "mode": mode,
        "rows": len(tasks),
        "distinct_root_qa_count": len(set(root_ids)),
        "repair_revision_rows": sum(bool((t.get('generation_provenance') or {}).get('qa_repair_lineage')) for t in tasks),
        "unresolved_quality_hold_task_ids": held_task_ids,
        "passed": not failures,
        "failures": failures,
        "domain_counts": dict(sorted(domain_counts.items())),
        "scorer_app_cardinality": dict(sorted(cardinality.items())),
        "top_scorer_app_combinations": dict(combinations.most_common(20)),
        "novelty_against_old_pool": {
            "baseline_bound": baseline_combinations is not None,
            "absent_combination_count": novel_combination_count,
            "absent_combination_fraction": (
                round(novel_combination_count / len(tasks), 6)
                if novel_combination_count is not None and tasks
                else None
            )
        },
        "prompt_user_chars": {
            "median": median(prompt_lengths) if prompt_lengths else 0,
            "p75": percentile(prompt_lengths, 0.75),
            "max": max(prompt_lengths, default=0)
        },
        "assertion_count": {"median": median(assertion_counts) if assertion_counts else 0, "max": max(assertion_counts, default=0)},
        "initial_state_app_membership": dict(sorted(initial_membership.items())),
        "initial_state_union_coverage": unions,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--taskset", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--mode", choices=("live", "terminal"), default="live")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.taskset, args.contract, args.output.parent):
        path.resolve().relative_to(ROOT)
    if args.output.exists():
        raise FileExistsError(args.output)
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    old_pool = contract.get("old_pool_reference") or {}
    baseline_path = ROOT / str(old_pool.get("taskset") or "")
    baseline_path.resolve().relative_to(ROOT)
    baseline_tasks = list(rows(baseline_path))
    if len(baseline_tasks) != int(old_pool.get("rows") or 0):
        raise ValueError("old pool reference cardinality mismatch")
    baseline_combinations = {
        "+".join(scorer_apps(task)) for task in baseline_tasks
    }
    result = audit(
        list(rows(args.taskset)),
        contract,
        args.mode,
        baseline_combinations=baseline_combinations,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "rows": result["rows"], "failure_count": len(result["failures"])}))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
