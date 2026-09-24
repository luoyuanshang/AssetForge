#!/usr/bin/env python3
"""Author stage entry point (plan-driven form).

Two ways to run the Author stage:

* ``python -m assetforge.tools.run_author --rubric ... --domain ... --run-root ...``
  runs one session from a Rubric directly;
* ``python -m assetforge.tools.run_constructed_qa_author --plan ... --cell ...``
  runs the same session from a frozen plan, which is how a batch is driven: the plan names the
  catalogue, the Rubric for each cell, and the run parameters, and each cell is bound by hash so
  a batch cannot silently change between runs.

This module is the plan-driven form; it resolves the cell and delegates to the same runner, so
there is exactly one implementation of the Author loop.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from assetforge.pipeline import operator_config  # noqa: E402
from assetforge.pipeline.construction_assets import require  # noqa: E402


def _bound(ref):
    """Resolve a {path, sha256} reference inside the repository, verifying the hash."""
    path = ROOT / ref["path"]
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == ref["sha256"],
            f"bound artifact drift: {ref['path']}")
    return path


def main(argv=None):
    operator_config.apply()
    (ROOT / "POLICY.md").read_text(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Run one Author session from a frozen plan")
    parser.add_argument("--plan", type=Path, required=True, help="the frozen plan JSON")
    parser.add_argument("--plan-sha256", required=True, help="hash of that plan")
    parser.add_argument("--cell", required=True, help="cell name from the plan")
    parser.add_argument("--ordinal", type=int, default=1, help="task ordinal within the cell")
    parser.add_argument("--arm", choices=["assets", "control"], default="assets",
                        help="'assets' composes from admitted assets; 'control' does not")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--max-turns", type=int,
                        default=int(operator_config.value("ASSETFORGE_AUTHOR_MAX_TURNS", "40")))
    parser.add_argument("--catalog-limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="resolve and verify the plan, then stop without calling a model")
    args = parser.parse_args(argv)

    require(hashlib.sha256(args.plan.read_bytes()).hexdigest() == args.plan_sha256,
            "plan drift: --plan-sha256 does not match the file")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    cells = plan.get("cells") or []
    cell = next((c for c in cells if c.get("cell") == args.cell), None)
    if cell is None:
        raise SystemExit(f"cell {args.cell!r} is not in the plan "
                         f"(available: {', '.join(str(c.get('cell')) for c in cells) or 'none'})")

    rubric_path = _bound(cell["rubric"])
    catalog_path = _bound(plan["catalog"]) if plan.get("catalog") else None

    print(f"cell        : {args.cell}  domain: {cell.get('domain')}  arm: {args.arm}")
    print(f"rubric      : {rubric_path.relative_to(ROOT)}")
    print(f"catalog     : {catalog_path.relative_to(ROOT) if catalog_path else '(none)'}")
    print(f"run root    : {args.run_root}")
    if args.dry_run:
        print("\ndry run: the plan, cell, Rubric and catalogue all verified; no model call made.")
        return 0

    # One implementation of the Author loop: delegate to the runner.
    from assetforge.tools import run_author

    forwarded = ["--rubric", str(rubric_path), "--domain", str(cell.get("domain") or "general"),
                 "--run-root", str(args.run_root), "--ordinal", str(args.ordinal),
                 "--max-turns", str(args.max_turns)]
    if catalog_path and args.arm == "assets":
        forwarded += ["--assets", str(ROOT / "assetforge/artifacts/construction_assets")]
    if args.catalog_limit:
        forwarded += ["--catalog-limit", str(args.catalog_limit)]
    return run_author.main(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
