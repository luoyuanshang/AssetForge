"""Summarise the public task structure without reproducing any test item.

The extractor intentionally never serializes task text, task names, application
names, record identifiers, assertion arguments, or initial-state values.  Its
output is a distribution over generic workflow properties that can constrain a
new executable generator without turning the public set into a paraphrase seed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Callable, Iterable


DOMAINS = ("sales", "marketing", "operations", "support", "finance", "hr")
READ_VERBS = {
    "find", "get", "list", "search", "query", "lookup", "read", "retrieve",
    "fetch", "download", "check",
}
WRITE_VERBS = {
    "add", "append", "archive", "assign", "cancel", "create", "delete", "invite",
    "like", "mark", "move", "post", "publish", "remove", "reply", "send", "set",
    "share", "tag", "update", "upload",
}


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# External task rows may name their tool list differently across runtime builds.  These are
# the spellings we accept when *reading* someone else's task; our own artifacts use
# ``tool_names``.
_TOOL_LIST_KEYS = ("tool_names", "tools", "zapier_tools", "api_tools")


def tool_list(info: dict) -> list:
    """The declared tool list of an external task row, under any accepted key."""
    if not isinstance(info, dict):
        return []
    for key in _TOOL_LIST_KEYS:
        value = info.get(key)
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value if isinstance(item, str)]
    return []


def _info(row: dict) -> dict:
    value = row.get("info", {})
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


def _tool_parts(name: str) -> tuple[str, str]:
    tokens = str(name).lower().split("_")
    for index, token in enumerate(tokens):
        if token in READ_VERBS | WRITE_VERBS:
            # The prefix is used only to count independent systems; it is never
            # emitted, so provider/product names cannot leak into the rubric.
            return "_".join(tokens[:index]) or "generic", token
    return "generic", "unknown"


def _assertion_family(assertion_type: str) -> str:
    value = assertion_type.lower()
    negative = any(token in value for token in ("not_", "_not", "absent", "unchanged"))
    if any(token in value for token in ("sent", "posted", "reply", "message")):
        family = "external_communication"
    elif any(token in value for token in ("deleted", "removed", "archived")):
        family = "deletion_or_archive"
    elif any(token in value for token in ("updated", "equals", "field_", "status")):
        family = "field_postcondition"
    elif any(token in value for token in ("exists", "created", "added")):
        family = "entity_postcondition"
    elif any(token in value for token in ("count", "total", "sum")):
        family = "aggregate_postcondition"
    else:
        family = "other_postcondition"
    return f"negative_{family}" if negative else family


def _percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)]


def _distribution(values: list[int]) -> dict:
    return {
        "min": min(values) if values else 0,
        "mean": round(mean(values), 4) if values else 0.0,
        "p50": _percentile(values, 0.50),
        "p90": _percentile(values, 0.90),
        "max": max(values) if values else 0,
    }


def _domain_summary(rows: Iterable[dict]) -> dict:
    task_count = 0
    tool_counts: list[int] = []
    system_counts: list[int] = []
    assertion_counts: list[int] = []
    read_counts: list[int] = []
    write_counts: list[int] = []
    negative_counts: list[int] = []
    action_histogram: Counter[str] = Counter()
    assertion_histogram: Counter[str] = Counter()
    motif_histogram: Counter[str] = Counter()
    for row in rows:
        task_count += 1
        info = _info(row)
        tools = tool_list(info)
        assertions = [item for item in info.get("assertions", []) if isinstance(item, dict)]
        parsed_tools = [_tool_parts(tool) for tool in tools]
        reads = sum(verb in READ_VERBS for _, verb in parsed_tools)
        writes = sum(verb in WRITE_VERBS for _, verb in parsed_tools)
        systems = {system for system, _ in parsed_tools if system}
        assertion_families = [_assertion_family(str(item.get("type", ""))) for item in assertions]
        negatives = sum(family.startswith("negative_") for family in assertion_families)
        tool_counts.append(len(tools))
        system_counts.append(len(systems))
        assertion_counts.append(len(assertions))
        read_counts.append(reads)
        write_counts.append(writes)
        negative_counts.append(negatives)
        action_histogram.update(verb for _, verb in parsed_tools)
        assertion_histogram.update(assertion_families)
        motifs = set()
        if reads and writes:
            motifs.add("read_before_write")
        if len(systems) >= 2:
            motifs.add("cross_system_join")
        if writes >= 2:
            motifs.add("multi_effect_execution")
        if negatives:
            motifs.add("negative_guard")
        if len(assertions) >= 5:
            motifs.add("multi_postcondition")
        if len(assertions) > max(1, writes):
            motifs.add("effect_fanout")
        motif_histogram.update(motifs)
    return {
        "task_count": task_count,
        "tools_per_task": _distribution(tool_counts),
        "independent_systems_per_task": _distribution(system_counts),
        "assertions_per_task": _distribution(assertion_counts),
        "read_capabilities_per_task": _distribution(read_counts),
        "write_capabilities_per_task": _distribution(write_counts),
        "negative_assertions_per_task": _distribution(negative_counts),
        "generic_action_frequency": dict(sorted(action_histogram.items())),
        "postcondition_family_frequency": dict(sorted(assertion_histogram.items())),
        "structural_motif_task_frequency": dict(sorted(motif_histogram.items())),
    }


def build_abstract_rubric(loader: Callable[[str], Iterable[dict]]) -> dict:
    domains = {domain: _domain_summary(loader(domain)) for domain in DOMAINS}
    total = sum(row["task_count"] for row in domains.values())
    payload = {
        "schema_version": "assetforge-abstract-rubric-v1",
        "source_scope": "public scored structure only",
        "source_task_count": total,
        "non_disclosure_contract": {
            "task_text_emitted": False,
            "task_identifiers_emitted": False,
            "application_names_emitted": False,
            "record_values_emitted": False,
            "assertion_arguments_emitted": False,
            "allowed_statistics": [
                "counts", "percentiles", "generic action families",
                "generic postcondition families", "structural motifs",
            ],
        },
        "domains": domains,
        "generation_contract": {
            "novel_world_namespace_required": True,
            "fictional_applications_only": True,
            "minimum_independent_evidence_sources": 2,
            "minimum_state_changing_operations": 1,
            "minimum_executable_postconditions": 3,
            "require_negative_guard_fraction": 0.5,
            "require_read_after_write_verification": True,
            "require_exact_world_replay": True,
            "forbid_test_item_paraphrase": True,
            "heldout_split_by_structural_signature": True,
        },
    }
    payload["content_sha256"] = hashlib.sha256(canonical(payload).encode()).hexdigest()
    validate_abstract_rubric(payload)
    return payload


def validate_abstract_rubric(payload: dict) -> None:
    if payload.get("schema_version") != "assetforge-abstract-rubric-v1":
        raise ValueError("unexpected rubric schema")
    if payload.get("source_task_count") != 600:
        raise ValueError("expected the six public scored domains (600 tasks)")
    forbidden_keys = {"prompt", "task", "example_id", "initial_state", "record_id", "value"}

    def walk(value: object) -> None:
        if isinstance(value, dict):
            overlap = forbidden_keys & set(value)
            if overlap:
                raise ValueError(f"rubric leaks source fields: {sorted(overlap)}")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    stored = payload.get("content_sha256")
    unhashed = dict(payload)
    unhashed.pop("content_sha256", None)
    if stored != hashlib.sha256(canonical(unhashed).encode()).hexdigest():
        raise ValueError("rubric content hash mismatch")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    import sys

    # The runtime is supplied by the operator; see native_runtime_interface.py.
    if getattr(args, "runtime_root", None):
        import os
        os.environ["ASSETFORGE_RUNTIME_ROOT"] = str(args.runtime_root.resolve())
    from .native_runtime_interface import domain_dataset

    payload = build_abstract_rubric(lambda domain: domain_dataset(domain))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "sha256": payload["content_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
