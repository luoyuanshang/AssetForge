"""Atomic source ownership for overlapping bounded repair dispatchers."""
from __future__ import annotations
import fcntl
import json
import os
from pathlib import Path
import tempfile

class RepairAlreadyClaimed(RuntimeError):
    pass

def claim_sources(ledger: Path, *, owner: str, sources: list[str]) -> None:
    if not owner or not sources or len(sources) != len(set(sources)):
        raise ValueError('unique nonempty repair sources and owner required')
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.with_suffix('.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        claims = json.loads(ledger.read_text()) if ledger.exists() else {}
        if any(s in claims and claims[s] != owner for s in sources):
            raise RepairAlreadyClaimed('repair source already claimed by another immutable group; no provider call')
        claims.update({s: owner for s in sources})
        fd, name = tempfile.mkstemp(prefix='.repair-claims-', dir=ledger.parent)
        try:
            with os.fdopen(fd, 'w') as handle:
                json.dump(claims, handle, ensure_ascii=False, sort_keys=True)
                handle.flush(); os.fsync(handle.fileno())
            os.replace(name, ledger)
        finally:
            if os.path.exists(name):
                os.unlink(name)
