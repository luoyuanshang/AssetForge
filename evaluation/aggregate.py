#!/usr/bin/env python3
"""Aggregate per-task records produced by run_evaluation.py.

    python evaluation/aggregate.py evaluation/out/tasks/*.json
    python evaluation/aggregate.py --allow-partial evaluation/out/results.json

The strict metric is the benchmark number, so this reports ``pass@1 = strict / total`` and
refuses to report a rate from an incomplete set unless ``--allow-partial`` is given.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

STRICT_KEY = "task_completed_correctly"


def load(path: Path):
    data = json.loads(path.read_text())
    if isinstance(data, dict) and "records" in data:
        return data["records"], data.get("summary") or {}
    if isinstance(data, list):
        return data, {}
    return [data], {}


def main(argv=None):
    p = argparse.ArgumentParser(description="Aggregate evaluation records")
    p.add_argument("paths", nargs="+")
    p.add_argument("--allow-partial", action="store_true",
                   help="report a rate even when records may be missing or errored")
    args = p.parse_args(argv)

    records, summaries = [], []
    for raw in args.paths:
        for path in sorted(Path().glob(raw)) if any(c in raw for c in "*?[") else [Path(raw)]:
            recs, summ = load(path)
            records.extend(recs)
            if summ:
                summaries.append(summ)

    if not records:
        print("no records", file=sys.stderr)
        return 2

    errored = [r for r in records if r.get("error")]
    strict = [r for r in records if r.get("strict")]
    total = len(records)
    by_domain = Counter()
    strict_by_domain = Counter()
    for r in records:
        d = r.get("domain") or "unknown"
        by_domain[d] += 1
        if r.get("strict"):
            strict_by_domain[d] += 1

    print(f"records        : {total}")
    print(f"errored        : {len(errored)}")
    print(f"strict metric  : {STRICT_KEY}")
    print(f"strict         : {len(strict)}")
    if errored and not args.allow_partial:
        print()
        print("refusing to report pass@1: some records carry an error. "
              "Re-run the missing tasks (--recover) or pass --allow-partial.")
        return 1
    print(f"pass@1         : {len(strict) / total:.4f}")
    if summaries:
        expected = {s.get("task_count") for s in summaries if s.get("task_count")}
        if len(expected) == 1 and total % next(iter(expected)) == 0:
            print(f"trials         : {total // next(iter(expected))}")
    print()
    print("by domain:")
    for d in sorted(by_domain):
        print(f"  {d:14s} strict {strict_by_domain[d]:4d} / {by_domain[d]:4d}"
              + (f"   {strict_by_domain[d] / by_domain[d]:.4f}" if by_domain[d] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
