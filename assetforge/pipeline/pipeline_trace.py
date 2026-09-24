"""One uniform, durable trace for every pipeline stage.

Goal (user, 2026-09-15): the whole pipeline must leave the same quality of trace
as the Author turns - "the whole flow looks like the Author had a complete trajectory".  Before this, per-item
evidence existed for Author turns (journals / turn_frames / snapshots /
provider_attempts) and, after 2026-09-14, for tool calls and compile attempts;
Reviewer, native, repair, collection and qualification had only summary receipts.

This module is the single writer for the uniform record.  Every stage writes:

* ``stage_start`` / ``stage_end`` with stage, root/item id, owner, pid, plan and
  binding hashes, model route, duration, outcome, error type/message/traceback,
  exit code, and the counters the stage reported;
* the **artifacts the stage produced**, enumerated from the stage output with
  size, mtime and sha256, so every claim can be traced back to bytes on disk.

Format: one JSON object per line in ``pipeline_trace.jsonl`` under the stage
output, append-only, single ``os.write`` + ``fsync`` per record.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import atexit
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "pipeline-trace-v1"
TRACE_NAME = "pipeline_trace.jsonl"
MAX_ARTIFACTS = 400
MAX_HASH_BYTES = 32 * 1024 * 1024
_FIELD_LIMIT = 16_000


def trace_path(run_root: os.PathLike[str] | str) -> Path:
    return Path(run_root) / TRACE_NAME


def _bounded(value: Any) -> Any:
    if isinstance(value, str):
        return value[:_FIELD_LIMIT]
    if isinstance(value, list):
        return [_bounded(item) for item in value[:60]]
    if isinstance(value, Mapping):
        return {str(key): _bounded(item) for key, item in list(value.items())[:80]}
    return value


def collect_artifacts(run_root: os.PathLike[str] | str, since_epoch: float,
                      *, limit: int = MAX_ARTIFACTS) -> list[dict[str, Any]]:
    """Enumerate files this stage wrote, with hashes, bounded in count and size."""
    rows: list[dict[str, Any]] = []
    root = Path(run_root)
    if not root.exists():
        return rows
    try:
        candidates = sorted(root.rglob("*"))
    except OSError:
        return rows
    for path in candidates:
        if len(rows) >= limit:
            break
        try:
            if not path.is_file():
                continue
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime < since_epoch:
            continue
        row: dict[str, Any] = {
            "path": str(path.relative_to(root)) if root in path.parents else str(path),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": None,
        }
        if stat.st_size <= MAX_HASH_BYTES:
            try:
                row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                row["sha256"] = None
        rows.append(row)
    return rows


def append(run_root: os.PathLike[str] | str, record: Mapping[str, Any]) -> Path | None:
    """Append one trace record; never raise into a stage."""
    path = trace_path(run_root)
    payload = {"schema_version": SCHEMA_VERSION,
               "observed_at_epoch": time.time(),
               "observed_at_cst": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
               "pid": os.getpid()}
    payload.update({str(key): _bounded(value) for key, value in record.items()})
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n"
        handle = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o664)
        try:
            os.write(handle, line.encode("utf-8"))
            os.fsync(handle)
        finally:
            os.close(handle)
    except OSError:
        return None
    return path


def install_finish(run_root: os.PathLike[str] | str | None, stage: str, **extra):
    """Return a ``finish(outcome, **fields)`` that writes exactly one stage_end.

    A stage that dies outside its own try/except (argparse ``SystemExit``, an
    import error, a signal-driven unwind) would otherwise leave ``stage_start``
    without ``stage_end`` - a gap the completeness gate must then treat as
    unknown.  Registering an ``atexit`` writer makes "started implies ended with a
    reason" true for every stage that adopts it, and the guard keeps the normal
    path from double-writing.
    """
    state = {'done': False, 'started': extra.pop('artifacts_since', None) or time.time()}

    def finish(outcome: str = 'completed', **fields):
        if state['done']:
            return None
        state['done'] = True
        record: dict[str, Any] = {
            'event': 'stage_end', 'stage': stage, 'outcome': outcome,
            'duration_seconds': round(time.time() - state['started'], 3),
        }
        record.update({k: v for k, v in extra.items()})
        record.update(fields)
        if run_root is not None:
            record['artifacts'] = collect_artifacts(run_root, state['started'])
        return append(run_root, record) if run_root is not None else None

    def _on_exit():
        finish('unfinished')

    atexit.register(_on_exit)
    return finish


OUTPUT_FLAGS = ('--output', '--out', '--output-root', '--run-root')


def argv_output(argv=None, flags=OUTPUT_FLAGS):
    argv = list(sys.argv if argv is None else argv)
    for flag in flags:
        if flag in argv:
            index = argv.index(flag)
            if index + 1 < len(argv):
                return argv[index + 1]
    return None


def guard_from_argv(stage: str, argv=None, **extra):
    """Start a stage trace and install its atexit finish, from the CLI alone."""
    output = argv_output(argv)
    if output is not None:
        append(output, dict({'event': 'stage_start', 'stage': stage,
                             'pid': os.getpid(), 'parent_pid': os.getppid()}, **extra))
    return install_finish(output, stage, **extra)


def read_trace(run_root: os.PathLike[str] | str) -> list[dict[str, Any]]:
    path = trace_path(run_root)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def completeness(run_root: os.PathLike[str] | str,
                 expected_stages: Iterable[str]) -> dict[str, Any]:
    """Fail-closed completeness report for one item's trace."""
    rows = read_trace(run_root)
    by_stage: dict[str, dict[str, bool]] = {}
    for row in rows:
        stage = str(row.get("stage") or "")
        event = str(row.get("event") or "")
        entry = by_stage.setdefault(stage, {"start": False, "end": False,
                                            "artifacts": False, "traceback": False})
        if event == "stage_start":
            entry["start"] = True
        elif event == "stage_end":
            entry["end"] = True
            if row.get("artifacts"):
                entry["artifacts"] = True
            if row.get("traceback"):
                entry["traceback"] = True
    missing: list[str] = []
    for stage in expected_stages:
        entry = by_stage.get(stage)
        if not entry or not entry["start"] or not entry["end"]:
            missing.append(stage)
    return {
        "run_root": str(run_root),
        "observed_stages": sorted(by_stage),
        "expected_stages": sorted(set(expected_stages)),
        "missing_stages": missing,
        "complete": not missing,
        "records": len(rows),
    }
