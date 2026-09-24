#!/usr/bin/env python3
"""Run the benchmark evaluation with official alignment.

This driver is intentionally thin: it constructs the runtime's own environment with the
runtime's own rubric and calls its own ``evaluate`` method, then reports the runtime's own
strict metric.  It does not reimplement scoring, prompts, tool routing or termination.

    python evaluation/run_evaluation.py \
        --model my-model --api-base-url https://host/v1 --api-key-env EVAL_API_KEY \
        --domains all --trials 1 --export-json evaluation/out/results.json

See evaluation/README.md for the full flag list and OFFICIAL_ALIGNMENT.md for the contract
this driver is required to honour.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from assetforge.pipeline import operator_config  # noqa: E402

operator_config.apply()          # resolve ASSETFORGE_* settings before anything reads them

import runtime_bridge as rb  # noqa: E402

STRICT_KEY = "task_completed_correctly"


def jsonable(value):
    """Make runtime objects (message classes, numpy scalars, dataclasses) file-safe.

    The runtime hands back its own message objects and dataset scalars; we keep the payload
    but convert anything unknown to a plain dict or string rather than failing at write time.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    for attr in ("model_dump", "to_dict", "dict"):
        fn = getattr(value, attr, None)
        if callable(fn):
            try:
                return jsonable(fn())
            except Exception:
                pass
    if hasattr(value, "__dict__"):
        try:
            return jsonable({k: v for k, v in vars(value).items() if not k.startswith("_")})
        except Exception:
            pass
    return str(value)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Benchmark evaluation with official alignment")
    p.add_argument("--model", default=operator_config.value("ASSETFORGE_MODEL"),
                   help="model id sent to the endpoint (default: $ASSETFORGE_MODEL)")
    p.add_argument("--api-base-url", default=operator_config.value("ASSETFORGE_API_BASE_URL"),
                   help="OpenAI-compatible base URL (default: $ASSETFORGE_API_BASE_URL)")
    p.add_argument("--api-key", default=operator_config.value("ASSETFORGE_API_KEY"),
                   help="API key (default: $ASSETFORGE_API_KEY)")
    p.add_argument("--api-key-var", dest="api_key_var", default="ASSETFORGE_API_KEY",
                   help="environment variable holding the API key")
    p.add_argument("--domains", default="all",
                   help="'all' or a comma-separated subset of the six business domains")
    p.add_argument("--num-examples", type=int, default=None, help="limit the number of tasks")
    p.add_argument("--max-steps", type=int, default=50, help="per-task turn budget (official: 50)")
    p.add_argument("--trials", type=int, default=1, help="independent trials to run")
    p.add_argument("--max-concurrent", type=int,
                   default=int(operator_config.value("ASSETFORGE_MAX_CONCURRENT", "32")),
                   help="in-flight tasks (default: $ASSETFORGE_MAX_CONCURRENT)")
    p.add_argument("--tasks", default=None, help="comma-separated task names to evaluate")
    p.add_argument("--toolset", default="api", help="runtime toolset (official: api)")
    p.add_argument("--api", default="chat_completions", choices=["chat_completions", "responses"],
                   help="endpoint style")
    p.add_argument("--reasoning-effort", default=None)
    p.add_argument("--extra-body", default=None, help="JSON object merged into sampling args")
    p.add_argument("--headers", default=None, help="JSON object of extra HTTP headers")
    p.add_argument("--search-top-k", type=int, default=None)
    p.add_argument("--recover", action="store_true", help="resume from per-task files")
    p.add_argument("--export-json", default=None, help="write aggregate + per-task records here")
    return p.parse_args(argv)


def resolve_domains(value):
    if value.strip().lower() in ("all", "*"):
        return list(rb.DEFAULT_DOMAINS)
    doms = [d.strip() for d in value.split(",") if d.strip()]
    unknown = [d for d in doms if d not in rb.DEFAULT_DOMAINS]
    if unknown:
        raise SystemExit(f"unknown domain(s): {', '.join(unknown)}; known: {', '.join(rb.DEFAULT_DOMAINS)}")
    return doms


def _info(row):
    """The runtime stores ``info`` as a JSON string; normalise it to a dict."""
    info = row.get("info")
    if isinstance(info, str):
        try:
            info = json.loads(info)
        except Exception:
            info = {}
    return info if isinstance(info, dict) else {}


def _row_name(row):
    info = _info(row)
    return info.get("task_name") or info.get("task_id") or row.get("example_id")


def _domain_of(name):
    """Task names are '<domain>.<name>'; fall back to the explicit field when present."""
    if isinstance(name, str) and "." in name:
        return name.split(".", 1)[0]
    return None


def select_rows(dataset, names):
    """Restrict the runtime's dataset to the named tasks.

    The runtime hands us its own ``datasets.Dataset``; that type is what it expects back, so
    we filter with its own API rather than converting to a list.
    """
    if not names:
        return dataset
    want = {n.strip() for n in names.split(",") if n.strip()}
    if hasattr(dataset, "filter"):
        present = [_row_name(row) for row in dataset]
        missing = want - set(present)
        if missing:
            raise SystemExit(f"task(s) not found in the dataset: {', '.join(sorted(missing))}")
        return dataset.filter(lambda row: _row_name(row) in want)
    picked = [row for row in dataset if _row_name(row) in want]
    missing = want - {_row_name(r) for r in picked}
    if missing:
        raise SystemExit(f"task(s) not found in the dataset: {', '.join(sorted(missing))}")
    return picked


def task_records(rows):
    """Flatten the runtime's rollout outputs into one record per task."""
    records = []
    for ro in rows:
        metrics = ro.get("metrics") or {}
        strict = float(metrics.get(STRICT_KEY, 0) or 0) == 1
        info = _info(ro)
        records.append(jsonable({
            "task": info.get("task_name") or info.get("task_id") or ro.get("example_id"),
            "domain": info.get("domain") or _domain_of(info.get("task_name") or ro.get("task")),
            "strict": strict,
            "reward": ro.get("reward"),
            "metrics": metrics,
            "prompt": ro.get("prompt"),
            "completion": ro.get("completion"),
            "assertions": ro.get("_assertion_results"),
            "usage": ro.get("_usage"),
            "error": ro.get("error"),
        }))
    return records


async def run_trial(args, dataset, domains):
    """One trial: build the runtime environment and let the runtime evaluate itself."""
    key = args.api_key or os.environ.get(args.api_key_var)
    if not key:
        raise SystemExit(f"no API key: pass --api-key or set {args.api_key_var}")
    os.environ[args.api_key_var] = key

    if args.api == "responses":
        cls = rb.responses_client_class()
        if cls is None:
            raise SystemExit("this runtime has no Responses client; use --api chat_completions")
    else:
        cls = rb.chat_client_class()
    client = cls(rb.client_config(api_key_var=args.api_key_var,
                                  api_base_url=args.api_base_url,
                                  timeout=float(os.environ.get("EVAL_REQUEST_TIMEOUT", "3600")),
                                  max_retries=int(os.environ.get("EVAL_SDK_MAX_RETRIES", "0"))))

    env = rb.environment_class()(dataset=dataset,
                                 rubric=rb.create_rubric(),
                                 max_turns=args.max_steps,
                                 toolset=args.toolset,
                                 search_top_k=args.search_top_k)
    sampling = dict(getattr(env, "sampling_args", {}) or {})
    if args.reasoning_effort:
        sampling["reasoning_effort"] = args.reasoning_effort
    if args.extra_body:
        sampling["extra_body"] = {**(sampling.get("extra_body") or {}), **json.loads(args.extra_body)}
    if args.headers:
        sampling["extra_headers"] = {**(sampling.get("extra_headers") or {}), **json.loads(args.headers)}

    started = time.time()
    result = await env.evaluate(
        client=client,
        model=args.model,
        sampling_args=sampling,
        num_examples=args.num_examples,
        rollouts_per_example=1,
        max_concurrent=args.max_concurrent,
        state_columns=["_usage", "_assertion_results", "_end_state", "_perf"],
    )
    try:
        await client.close()
    except Exception:
        pass
    rows = result["outputs"] if isinstance(result, dict) else result
    return task_records(rows), time.time() - started


async def main_async(args):
    if not rb.is_available():
        raise SystemExit(
            "benchmark runtime not importable.\n"
            "Install the official runtime package, or set ASSETFORCE_RUNTIME_ROOT to the "
            "directory containing its package, then retry.")
    domains = resolve_domains(args.domains)
    dataset = rb.combined_dataset(domains)
    dataset = select_rows(dataset, args.tasks)
    selected_count = len(dataset)
    if args.num_examples is not None:
        selected_count = min(selected_count, args.num_examples)
    print(f"runtime pin : {rb.runtime_pin()}")
    print(f"domains     : {', '.join(domains)}")
    print(f"tasks       : {selected_count}")
    print(f"model       : {args.model}   endpoint: {args.api_base_url or '(provider default)'}")
    print(f"trials      : {args.trials}   max_steps: {args.max_steps}   concurrency: {args.max_concurrent}")
    print()

    out_root = Path(args.export_json).resolve().parent if args.export_json else None
    if out_root:
        (out_root / "tasks").mkdir(parents=True, exist_ok=True)

    per_trial, all_records = [], []
    for trial in range(1, args.trials + 1):
        todo = dataset
        done = {}
        if args.recover and out_root:
            for f in sorted((out_root / "tasks").glob("*.json")):
                rec = json.loads(f.read_text())
                done[rec.get("task")] = rec
            todo = [r for r in dataset
                    if ((r.get('info') or {}).get('task_name') or (r.get('info') or {}).get('task_id')
                        or r.get('example_id')) not in done]
            print(f"trial {trial}: recovering {len(done)} task(s), {len(todo)} remaining")
        records, seconds = (list(done.values()), 0.0) if not todo else await run_trial(args, todo, domains)
        if todo:
            records = list(done.values()) + records
        strict = sum(1 for r in records if r["strict"])
        total = len(records)
        rate = (strict / total) if total else None
        per_trial.append({"trial": trial, "total": total, "strict": strict, "pass_at_1": rate,
                          "duration_seconds": round(seconds, 1)})
        all_records.extend(records)
        print(f"trial {trial}: strict {strict}/{total}"
              + (f"  pass@1 = {rate:.4f}" if rate is not None else ""))
        if out_root:
            for rec in records:
                name = str(rec.get("task") or "task").replace("/", "_")
                (out_root / "tasks" / f"trial{trial}-{name}.json").write_text(
                    json.dumps(rec, ensure_ascii=False, indent=1))

    complete = all(t["total"] == selected_count for t in per_trial)
    mean_rate = (sum(t["pass_at_1"] or 0 for t in per_trial) / len(per_trial)) if complete else None
    by_domain = {}
    for rec in all_records:
        d = rec.get("domain") or "unknown"
        slot = by_domain.setdefault(d, {"total": 0, "strict": 0})
        slot["total"] += 1
        slot["strict"] += 1 if rec.get("strict") else 0
    summary = {
        "runtime_pin": rb.runtime_pin(),
        "by_domain": by_domain,
        "model": args.model,
        "api_base_url": args.api_base_url,
        "domains": domains,
        "task_count": selected_count,
        "max_steps": args.max_steps,
        "strict_metric": STRICT_KEY,
        "trials": per_trial,
        "pass_at_1_mean_over_trials": mean_rate,
        "complete": complete,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    print()
    print(f"tasks evaluated : {selected_count}")
    print(f"strict metric   : {STRICT_KEY}")
    if mean_rate is not None:
        print(f"pass@1 (mean)   : {mean_rate:.4f}")
    else:
        print("pass@1 (mean)   : n/a (some trial was incomplete)")
    if args.export_json:
        out = Path(args.export_json).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"summary": summary, "records": all_records},
                                  ensure_ascii=False, indent=1))
        print(f"written         : {out}")
    return 0 if complete else 1


def main(argv=None):
    args = parse_args(argv)
    if not args.model:
        raise SystemExit("no model: pass --model or set ASSETFORGE_MODEL")
    if not args.api_key and not os.environ.get(args.api_key_var):
        raise SystemExit("no API key: pass --api-key or set ASSETFORGE_API_KEY")
    try:
        return asyncio.run(main_async(args))
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    raise SystemExit(main())
