#!/usr/bin/env python3
"""Bounded-concurrency scheduling for whole-task reviewers; does not replace reviewer judgement."""
from __future__ import annotations

import argparse
from collections import Counter, deque
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from assetforge.pipeline.qa_review_lineage import validate_author_rubric
PYTHON = Path(os.environ.get("ASSETFORGE_RUNTIME_VENV", sys.executable))
REVIEWER = ROOT / "assetforge/tools/run_agentic_markdown_reviewer.py"
PLAN_SCHEMA = "agentic-markdown-reviewer-batch-plan-v3"
SUMMARY_SCHEMA = "agentic-markdown-reviewer-batch-summary-v3"
DOMAINS = ("sales", "marketing", "operations", "support", "finance", "hr")
DEFAULT_REFERENCE_TASKS = {
    "sales": "sales.multi_hop_lookup",
    "marketing": "marketing.social_engagement_response",
    "operations": "operations.asana_fire_drill",
    "support": "support.zendesk_sf_case_sync",
    "finance": "finance.invoice_email_extract",
    "hr": "hr.training_compliance",
}


def _stamp() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y%m%dT%H%M%S%z")


def _storage_snapshot() -> dict[str, int | bool]:
    def free(path: Path) -> int:
        value = os.statvfs(path)
        return value.f_bavail * value.f_frsize
    root_free, data_free = free(Path('/')), free(ROOT)
    return {'root_free_bytes':root_free, 'data_free_bytes':data_free,
            'threshold_bytes':10*1024**3, 'hard_stop':data_free<10*1024**3,
            'root_low_advisory_only':root_free<10*1024**3}


def _admission_limit(configured: int, elapsed_seconds: float) -> int:
    """Above a concurrency of 50, step up by 50 every three minutes from 50."""

    if configured <= 50:
        return configured
    ramp_steps = max(0, int(elapsed_seconds // 180))
    return min(configured, 50 + ramp_steps * 50)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,100}", value):
        raise ValueError("controller id must use safe filename characters")
    return value


def _review_id(controller_id: str, task_id: str) -> str:
    """Keep a human-readable prefix while hashing the full task ID to avoid long-prefix collisions."""

    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:12]
    value = f"{controller_id[:42]}-{task_id[:38]}-{digest}"
    if len(value) > 96:
        raise AssertionError("review id budget exceeded")
    return value


def _inside(path: Path, root: Path, *, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} must remain under {root}") from exc
    return resolved


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_once(path: Path, value: Any) -> None:
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _proc_start_ticks(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[21]
    except (OSError, IndexError):
        return ""


def _acquire_lock(path: Path, controller_id: str) -> str:
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    token = uuid4().hex
    for attempt in range(2):
        payload = {
            "schema_version": "agentic-markdown-reviewer-batch-lock-v1",
            "controller_id": controller_id,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "process_start_ticks": _proc_start_ticks(os.getpid()),
            "owner_token": token,
            "created_at": _stamp(),
        }
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        except FileExistsError:
            if attempt:
                raise RuntimeError("another process owns this review controller")
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                pid = int(existing.get("pid"))
                stale = (
                    existing.get("hostname") == socket.gethostname()
                    and (
                        not _proc_start_ticks(pid)
                        or existing.get("process_start_ticks") != _proc_start_ticks(pid)
                    )
                )
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                stale = True
            if stale:
                path.unlink(missing_ok=True)
                continue
            raise RuntimeError("another process owns this review controller")
        else:
            try:
                os.write(fd, (json.dumps(payload, ensure_ascii=False) + "\n").encode())
                os.fsync(fd)
            finally:
                os.close(fd)
            _fsync_directory(path.parent)
            return token
    raise RuntimeError("failed to acquire review controller lock")


def _release_lock(path: Path, token: str) -> None:
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if current.get("owner_token") == token:
        path.unlink(missing_ok=True)
        _fsync_directory(path.parent)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"taskset row {number} is not an object")
        rows.append(row)
    if not rows:
        raise ValueError("taskset is empty")
    return rows


def _view_task_index(paths: list[Path], *, lineage: str) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in paths:
        for row in _read_jsonl(path):
            task_id = row.get("task_id")
            if not isinstance(task_id, str):
                raise ValueError(f"{lineage} view row lacks task_id: {path}")
            if task_id in index:
                raise ValueError(f"duplicate {lineage} trajectory for {task_id}")
            index[task_id] = path
    return index


def _select_tasks(
    rows: list[dict[str, Any]], requested_task_ids: list[str] | None
) -> list[dict[str, Any]]:
    if not requested_task_ids:
        return rows
    if len(set(requested_task_ids)) != len(requested_task_ids):
        raise ValueError("--task-id values must be unique")
    by_id = {str(row.get("task_id")): row for row in rows}
    missing = [task_id for task_id in requested_task_ids if task_id not in by_id]
    if missing:
        raise ValueError(f"requested task IDs are absent from taskset: {missing}")
    return [by_id[task_id] for task_id in requested_task_ids]


def _single_target_result(root: Path, domain: str) -> Path:
    candidates = sorted(
        (root / f"{domain}_chunks" / "chunk_0").glob(
            "*/benchmark-result.json"
        )
    )
    if len(candidates) != 1:
        raise ValueError(
            f"expected one public reference result for {domain}, found {len(candidates)}"
        )
    return candidates[0].resolve()


def _source_paths(task: dict[str, Any], author_root: Path) -> dict[str, Path | str]:
    task_id = task.get("task_id")
    domain = task.get("domain_label")
    provenance = task.get("generation_provenance")
    source = provenance.get("source_candidate_relative_path") if isinstance(provenance, dict) else None
    if not isinstance(task_id, str) or not re.fullmatch(
        r"[A-Za-z0-9._-]{3,100}", task_id
    ):
        raise ValueError("taskset contains an invalid agentic task_id")
    if domain not in DOMAINS:
        raise ValueError(f"task {task_id} has unsupported domain {domain!r}")
    if not isinstance(source, str):
        raise ValueError(f"task {task_id} lacks author candidate provenance")
    candidate = _inside(ROOT / source, author_root, label="author candidate")
    if candidate.parent.name != "candidates" or candidate.suffix != ".md":
        raise ValueError(f"task {task_id} has an unexpected candidate path")
    stem = candidate.stem
    generated = candidate.parent.parent / "tasks" / f"{stem}.json"
    receipt = candidate.parent.parent / "audits" / f"{stem}.multiturn-author.json"
    regression = candidate.parent.parent / "audits" / f"{stem}.native-regression.json"
    for label, path in {
        "candidate": candidate,
        "generated task": generated,
        "author receipt": receipt,
        "native regression": regression,
    }.items():
        if not path.is_file():
            raise FileNotFoundError(f"{label} missing for {task_id}: {path}")
    generated_body = json.loads(generated.read_text(encoding="utf-8"))
    if generated_body.get("task_id") != task_id:
        raise ValueError(f"compiled task identity mismatch for {task_id}")
    return {
        "task_id": task_id,
        "domain": domain,
        "candidate": candidate,
        "generated_task": generated,
        "author_receipt": receipt,
        "native_regression": regression,
    }


def _receipt_complete(review_root: Path, review_id: str, task_id: str) -> bool:
    receipt_path = review_root / "audits" / f"{review_id}.markdown-reviewer.json"
    if not receipt_path.is_file():
        return False
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        memo = ROOT / receipt["memo"]["relative_path"]
        packet = ROOT / receipt["packet"]["relative_path"]
        seal = ROOT / receipt["completion_seal"]["relative_path"]
        binding_task = receipt["packet"]["source_binding"]["generated_task"]["task_id"]
        return (
            receipt.get("status") == "completed"
            and binding_task == task_id
            and memo.is_file()
            and packet.is_file()
            and seal.is_file()
            and _file_sha256(memo) == receipt["memo"]["sha256"]
            and _file_sha256(packet) == receipt["packet"]["sha256"]
            and _file_sha256(seal) == receipt["completion_seal"]["sha256"]
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _child_command(item: dict[str, Any], *, args: argparse.Namespace) -> list[str]:
    command = [
        str(PYTHON),
        str(REVIEWER),
        "--rubric", str(args.rubric),
        "--candidate", str(item["candidate"]),
        "--generated-task", str(item["generated_task"]),
        "--target-result", str(item["target_result"]),
        "--target-task", str(item["reference_task"]),
        "--author-receipt", str(item["author_receipt"]),
        "--native-regression", str(item["native_regression"]),
        "--lexical-audit", str(item["lexical_audit"]),
        "--reviewer-prompt", str(
            getattr(
                args,
                "reviewer_prompt",
                ROOT / "assetforge/artifacts/reviewer_prompts/"
                "automation_qa_reviewer_v1_20260902.md",
            )
        ),
        "--run-root", str(args.review_run_root),
        "--review-id", str(item["review_id"]),
        "--max-tool-rounds", str(args.max_tool_rounds),
        "--timeout", str(args.provider_timeout),
    ]
    if args.accepted_corpus_catalog is not None:
        command.extend([
            "--accepted-corpus-catalog",
            str(args.accepted_corpus_catalog),
        ])
    if args.omit_public_task_examples:
        command.append("--omit-public-task-examples")
    return command


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except ProcessLookupError:
        return
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.wait(timeout=10)


def run(args: argparse.Namespace) -> dict[str, Any]:
    (ROOT / "PROJECT_CONSTRAINTS.md").read_text(encoding="utf-8")
    args.controller_id = _safe_id(args.controller_id)
    for name in ("rubric", "taskset", "lexical_audit"):
        setattr(args, name, _inside(Path(getattr(args, name)), ROOT, label=name))
    if args.accepted_corpus_catalog is not None:
        args.accepted_corpus_catalog = _inside(
            Path(args.accepted_corpus_catalog),
            ROOT,
            label="accepted corpus catalog",
        )
        if (
            not args.accepted_corpus_catalog.is_file()
            or args.accepted_corpus_catalog.suffix.lower() != ".md"
        ):
            raise ValueError("accepted corpus catalog must be a Markdown file")
    args.author_run_root = _inside(
        Path(args.author_run_root), ROOT / "assetforge/runs", label="author root"
    )
    args.review_run_root = _inside(
        Path(args.review_run_root), ROOT / "assetforge/runs", label="review root"
    )
    args.target_root = _inside(Path(args.target_root), ROOT, label="target root")
    if not 1 <= args.max_concurrent <= 300:
        raise ValueError("max_concurrent must be within [1, 300]")
    if args.provider_timeout < 60 or args.item_timeout < args.provider_timeout:
        raise ValueError("invalid provider/item timeout")

    items: list[dict[str, Any]] = []
    selected_tasks = _select_tasks(_read_jsonl(args.taskset), args.task_id)
    for task in selected_tasks:
        item = _source_paths(task, args.author_run_root)
        validate_author_rubric(item['author_receipt'], args.rubric)
        domain = str(item["domain"])
        task_id = str(item["task_id"])
        item.update({
            "review_id": _review_id(args.controller_id, task_id),
            "reference_task": DEFAULT_REFERENCE_TASKS[domain],
            "target_result": _single_target_result(args.target_root, domain),
        })
        lexical_root = Path(args.lexical_audit)
        lexical_path = (
            lexical_root
            / f"{Path(str(item['candidate'])).stem}.lexical-contamination.json"
            if lexical_root.is_dir()
            else lexical_root
        )
        if not lexical_path.is_file():
            raise FileNotFoundError(
                f"lexical audit missing for {task_id}: {lexical_path}"
            )
        item["lexical_audit"] = lexical_path
        items.append(item)

    controller_root = args.review_run_root / "controller"
    plan_path = controller_root / f"{args.controller_id}.plan.json"
    plan_body = {
        "schema_version": PLAN_SCHEMA,
        "controller_id": args.controller_id,
        "taskset": {"path": args.taskset.relative_to(ROOT).as_posix(), "sha256": _file_sha256(args.taskset)},
        "rubric": {"path": args.rubric.relative_to(ROOT).as_posix(), "sha256": _file_sha256(args.rubric)},
        "qa_review_contract": "qa-only-official-runtime-v3",
        "student_trajectories_included": False,
        "public_task_examples_inlined": not args.omit_public_task_examples,
        "lexical_audit_source": (
            {
                "kind": "per-task-directory",
                "path": args.lexical_audit.relative_to(ROOT).as_posix(),
            }
            if args.lexical_audit.is_dir()
            else {
                "kind": "shared-corpus-audit",
                "path": args.lexical_audit.relative_to(ROOT).as_posix(),
                "sha256": _file_sha256(args.lexical_audit),
            }
        ),
        "accepted_corpus_catalog": (
            None
            if args.accepted_corpus_catalog is None
            else {
                "path": args.accepted_corpus_catalog.relative_to(ROOT).as_posix(),
                "sha256": _file_sha256(args.accepted_corpus_catalog),
            }
        ),
        "max_tool_rounds": args.max_tool_rounds,
        "provider_timeout": args.provider_timeout,
        "requested_task_ids": list(args.task_id or []),
        "items": [
            {
                "task_id": item["task_id"],
                "domain": item["domain"],
                "review_id": item["review_id"],
                "reference_task": item["reference_task"],
                **{
                    key: {"path": item[key].relative_to(ROOT).as_posix(), "sha256": _file_sha256(item[key])}
                    for key in (
                        "candidate", "generated_task", "author_receipt", "native_regression",
                        "target_result", "lexical_audit",
                    )
                },
            }
            for item in items
        ],
    }
    plan_hash = _sha256_json(plan_body)
    plan = {**plan_body, "created_at": _stamp(), "plan_sha256": plan_hash}
    if plan_path.exists():
        if not args.resume:
            raise FileExistsError("review batch plan exists; use --resume")
        existing = json.loads(plan_path.read_text(encoding="utf-8"))
        existing_body = {k: v for k, v in existing.items() if k not in {"created_at", "plan_sha256"}}
        if existing.get("plan_sha256") != _sha256_json(existing_body) or existing_body != plan_body:
            raise ValueError("resume inputs differ from immutable review plan")
        plan = existing
    else:
        _write_once(plan_path, plan)

    if getattr(args, 'preflight_only', False):
        return {'passed': True, 'provider_calls': 0, 'planned_task_count': len(items),
                'plan_path': str(plan_path.relative_to(ROOT)), 'plan_sha256': plan['plan_sha256']}

    lock_path = controller_root / f"{args.controller_id}.lock.json"
    lock_token = _acquire_lock(lock_path, args.controller_id)
    pending = deque(
        item for item in items
        if not _receipt_complete(args.review_run_root, str(item["review_id"]), str(item["task_id"]))
    )
    precompleted = len(items) - len(pending)
    running: dict[int, tuple[subprocess.Popen[bytes], dict[str, Any], float]] = {}
    statuses: Counter[str] = Counter({"completed_before_start": precompleted})
    interrupted = False
    stop_reason = None
    storage_at_stop = None
    controller_started_monotonic = time.monotonic()
    peak_admission_limit = min(args.max_concurrent, 50)
    peak_active_children = 0

    def stop_handler(_signum: int, _frame: Any) -> None:
        nonlocal interrupted, stop_reason
        interrupted = True
        stop_reason = stop_reason or 'external_signal'

    old_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    for sig in old_handlers:
        signal.signal(sig, stop_handler)
    try:
        while (pending or running) and not interrupted:
            storage = _storage_snapshot()
            if storage['hard_stop']:
                interrupted = True
                stop_reason = 'storage_hard_stop'
                storage_at_stop = storage
                break
            admission_limit = _admission_limit(
                args.max_concurrent,
                time.monotonic() - controller_started_monotonic,
            )
            peak_admission_limit = max(peak_admission_limit, admission_limit)
            while pending and len(running) < admission_limit:
                item = pending.popleft()
                process = subprocess.Popen(
                    _child_command(item, args=args),
                    cwd=ROOT,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                running[process.pid] = (process, item, time.monotonic())
                peak_active_children = max(peak_active_children, len(running))
            for pid, (process, item, started) in list(running.items()):
                code = process.poll()
                if code is None and time.monotonic() - started > args.item_timeout:
                    _terminate(process)
                    statuses["timed_out"] += 1
                    del running[pid]
                    continue
                if code is None:
                    continue
                if code == 0 and _receipt_complete(
                    args.review_run_root, str(item["review_id"]), str(item["task_id"])
                ):
                    statuses["completed"] += 1
                else:
                    statuses["failed"] += 1
                del running[pid]
            if pending or running:
                time.sleep(0.25)
    finally:
        for process, _item, _started in running.values():
            _terminate(process)
            statuses[
                "interrupted" if interrupted else "controller_cleanup_terminated"
            ] += 1
        running.clear()
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        _release_lock(lock_path, lock_token)

    statuses["not_started"] += len(pending)
    summary = {
        "schema_version": SUMMARY_SCHEMA,
        "controller_id": args.controller_id,
        "created_at": _stamp(),
        "plan": {"path": plan_path.relative_to(ROOT).as_posix(), "sha256": _file_sha256(plan_path)},
        "max_concurrent": args.max_concurrent,
        "admission_ramp": {
            "enabled": args.max_concurrent > 50,
            "initial_limit": min(args.max_concurrent, 50),
            "step": 50,
            "interval_seconds": 180,
            "peak_limit": peak_admission_limit,
        },
        "peak_active_children": peak_active_children,
        "total": len(items),
        "status_counts": dict(statuses),
        "interrupted": interrupted,
        "stop_reason": stop_reason,
        "storage_at_stop": storage_at_stop,
        "owned_processes_remaining": 0,
    }
    summary["content_sha256"] = _sha256_json(summary)
    summary_path = controller_root / "summaries" / f"{args.controller_id}-{_stamp()}.json"
    _write_once(summary_path, summary)
    print(json.dumps({"summary": summary_path.relative_to(ROOT).as_posix(), **summary["status_counts"]}, ensure_ascii=False))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rubric", type=Path, required=True)
    parser.add_argument("--taskset", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--author-run-root", type=Path, required=True)
    parser.add_argument("--lexical-audit", type=Path, required=True)
    parser.add_argument("--accepted-corpus-catalog", type=Path)
    parser.add_argument(
        "--reviewer-prompt",
        type=Path,
        required=True,
        help="A versioned reviewer prompt, frozen and independent of the Author Rubric.",
    )
    parser.add_argument(
        "--omit-public-task-examples",
        action="store_true",
        help="Expansion mode does not inline the official verbatim statement into the per-task reviewer prompt.",
    )
    parser.add_argument("--review-run-root", type=Path, required=True)
    parser.add_argument("--controller-id", required=True)
    parser.add_argument(
        "--task-id",
        action="append",
        help="Review only the named tasks in the taskset; repeatable, and the plan binds exact order.",
    )
    parser.add_argument("--max-concurrent", type=int, default=4)
    parser.add_argument("--max-tool-rounds", type=int, default=12)
    parser.add_argument("--provider-timeout", type=int, default=3600)
    parser.add_argument("--item-timeout", type=int, default=5400)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--preflight-only", action="store_true",
                        help="Bind all original inputs and save a plan without launching Reviewer children.")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        run(parse_args())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
