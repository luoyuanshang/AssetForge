"""Generate, compile, review and publish one business-automation QA."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from assetforge.agent.author_runner import ModelEndpoint
from assetforge.pipeline.assets import AssetLibrary
from assetforge.pipeline.flow import run_pipeline
from assetforge.pipeline.runtime import load_runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rubric", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task-id", default="task-001")
    parser.add_argument("--assets", nargs="+")
    parser.add_argument("--runtime", required=True, help="'demo' or an importable module:factory")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--resume", action="store_true", help="Continue a run with exactly matching bound inputs")
    parser.add_argument("--business-time", default="2026-01-15T09:00:00Z")
    args = parser.parse_args()
    library = AssetLibrary()
    runtime = load_runtime(args.runtime)
    assets = args.assets
    if assets is None and args.runtime == "demo":
        assets = ["sheet_row_state"]
    result = run_pipeline(
        rubric=args.rubric.read_text(), library=library, runtime=runtime,
        author=ModelEndpoint(role="author"), reviewer=ModelEndpoint(role="reviewer"),
        output=args.output, task_id=args.task_id, asset_ids=assets, attempts=args.attempts,
        seed=args.seed, business_time=args.business_time, resume=args.resume,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
