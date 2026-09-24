"""Read a stable registry snapshot before executing an active entry.

Finite retries cover concurrent in-place edits. Persistent corruption, duplicate
keys, inactive entries and malformed argv never authorize execution.
"""
from __future__ import annotations

import os
from pathlib import Path
import time
import yaml
from yaml.constructor import ConstructorError

ROOT = Path(__file__).resolve().parents[2]


class UniqueLoader(yaml.CSafeLoader):
    pass


def _mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ConstructorError(None, None, "duplicate registry key", key_node.start_mark)
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _signature(path):
    stat = path.stat()
    return stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def read_registry(path=None, *, attempts=5, retry_seconds=0.2):
    """Read the optional command registry.

    The registry is a convenience for operator-owned deployments: it records which commands are
    registered and under what conditions they may run.  It is not required to use the stages
    directly, so a missing registry yields an empty one rather than an error.
    """
    path = Path(path or ROOT / "commands.yaml")
    if not path.exists():
        return {}
    if not 1 <= attempts <= 10 or not 0 <= retry_seconds <= 1:
        raise ValueError("registry retry budget out of bounds")
    for attempt in range(attempts):
        try:
            before = _signature(path)
            raw = path.read_bytes()
            if before != _signature(path) or len(raw) != before[1]:
                raise ValueError("registry changed during read")
            value = yaml.load(raw.decode("utf-8"), Loader=UniqueLoader)
            if before != _signature(path):
                raise ValueError("registry changed during parse")
            if not isinstance(value, dict) or not isinstance(value.get("commands"), dict):
                raise ValueError("registry must contain commands mapping")
            return value["commands"]
        except (OSError, UnicodeError, yaml.YAMLError, ValueError, TypeError):
            if attempt + 1 < attempts:
                time.sleep(retry_seconds)
    # Never include parser fragments: a registry may contain environment values.
    raise RuntimeError("No stable valid command registry after bounded retries; nothing executed")


def active_command(name, *, path=None):
    row = read_registry(path).get(name)
    if not isinstance(row, dict) or row.get("status") != "active":
        raise ValueError("command entry is missing or not active")
    argv = row.get("command")
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
        raise ValueError("active command argv is invalid")
    return list(argv)


def exec_active(name):
    argv = active_command(name)
    os.execvpe(argv[0], argv, os.environ)


def start_active_detached(name, receipt_dir):
    """Start an explicitly bounded registered job with project-owned file I/O.

    A terminal disconnection must not close a monitor's stdout or send a signal
    to the business controller's session. The registered job, not this launcher,
    retains its own finite deadline, signal handling and child cleanup.
    """
    import hashlib
    import json
    import subprocess
    from datetime import datetime

    row = read_registry().get(name)
    if not isinstance(row, dict) or row.get("status") != "active":
        raise ValueError("command entry is missing or not active")
    if row.get("owner") != "codex-root" or not row.get("stop_condition"):
        raise ValueError("detached job must have an explicit owner and stop condition")
    argv = row.get("command")
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
        raise ValueError("active command argv is invalid")
    directory = Path(receipt_dir).resolve()
    directory.relative_to((ROOT / "assetforge/runs").resolve())
    directory.mkdir(parents=True, exist_ok=False)  # duplicate launches fail closed
    with (directory / "stdout.log").open("x") as stdout, (directory / "stderr.log").open("x") as stderr:
        process = subprocess.Popen(argv, cwd=ROOT, env=os.environ.copy(),
            stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
            start_new_session=True, close_fds=True)
    receipt = dict(command_id=name, owner=row["owner"], pid=process.pid,
        created_at=datetime.now().astimezone().isoformat(),
        argv_sha256=hashlib.sha256(json.dumps(argv, ensure_ascii=False).encode()).hexdigest(),
        stop_condition=row["stop_condition"], independent_session=True,
        project_file_stdio=True, launch_only_not_completion=True)
    with (directory / "launch.json").open("x") as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2)
    return receipt
