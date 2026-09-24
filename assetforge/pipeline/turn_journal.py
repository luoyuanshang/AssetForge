"""Per-turn, append-only, hash-chained agent trajectory journal.

Design goals:

* every assistant message, tool call and tool result is its own fsync frame;
* each frame binds run/model/domain/task/trial/attempt and the config hash;
* resumption happens only at a complete tool-result boundary;
* if the crashed tail already performed partial side effects, blind replay is forbidden;
* a finished trajectory is fixed by an append-forbidding seal;
* provider request IDs, errors and retry history live in a separate hash-chained file.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterator, Mapping

from .compressed_jsonl import compressed_path, open_binary, resolve_read_path


FRAME_SCHEMA = "agent-turn-append-only-frame-v1"
PROVIDER_EVENT_SCHEMA = "agent-provider-attempt-event-v1"
PROVIDER_EVENT_TYPES = {
    "request_started",
    "request_succeeded",
    "request_failed",
    "same_route_transport_retry_scheduled",
    "route_fallback_activated",
    "reviewer_provider_admitted",
}
LEGACY_SEAL_SCHEMA = "agent-turn-journal-completed-seal-v1"
SEAL_SCHEMA = "agent-turn-journal-completed-seal-v2"
GENESIS_HASH = "0" * 64
SNAPSHOT_REF_SCHEMA = "agent-turn-journal-gzip-json-blob-v1"
_SURROGATE_PATTERN = re.compile(r"[\ud800-\udfff]")


class JournalIntegrityError(RuntimeError):
    """The journal is truncated, modified, mixed with another config, or malformed."""


class JournalSealedError(RuntimeError):
    """A finished trajectory may not be appended to."""


class UnsafeResumeError(RuntimeError):
    """The tail already has partial side effects; replaying from an old boundary is unsafe."""


def canonical_json(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    # Python permits isolated UTF-16 surrogate code points in ``str`` values,
    # while UTF-8 does not.  An upstream API payload can therefore be valid as
    # an in-memory object but fail while the journal hashes or persists it.
    # Escape only surrogate code units; ordinary ASCII, CJK, and non-BMP
    # Unicode retain their historical bytes, so existing hash chains remain
    # valid.
    return _SURROGATE_PATTERN.sub(
        lambda match: f"\\u{ord(match.group(0)):04x}", serialized
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _safe_component(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "unknown")).strip("._")
    return (text or "unknown")[:96]


def _fsync_directory(path: Path) -> None:
    directory = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class JournalIdentity:
    run_id: str
    model_alias: str
    model_name: str
    domain: str
    task_id: str
    trial_index: int
    config_sha256: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and bool(value.strip())
            for value in (
                self.run_id,
                self.model_alias,
                self.model_name,
                self.domain,
                self.task_id,
            )
        ):
            raise ValueError("journal identity strings must be non-empty")
        if type(self.trial_index) is not int or self.trial_index < 0:
            raise ValueError("trial_index must be a non-negative integer")
        if not re.fullmatch(r"[0-9a-f]{64}", self.config_sha256):
            raise ValueError("config_sha256 must be a lowercase SHA-256")

    def metadata(self, *, attempt_index: int) -> dict[str, Any]:
        if type(attempt_index) is not int or attempt_index < 0:
            raise ValueError("attempt_index must be a non-negative integer")
        return {
            "run_id": self.run_id,
            "model_alias": self.model_alias,
            "model_name": self.model_name,
            "domain": self.domain,
            "task_id": self.task_id,
            "trial_index": self.trial_index,
            "attempt_index": attempt_index,
            "config_sha256": self.config_sha256,
        }


@dataclass(frozen=True)
class ResumeBoundary:
    state: dict[str, Any]
    trace: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    source: str
    last_frame_sha256: str
    discarded_read_only_tail: bool = False
    terminal: bool = False


class TurnJournal:
    def __init__(
        self,
        root: Path,
        identity: JournalIdentity,
        *,
        attempt_index: int,
        compact_snapshots: bool = False,
    ) -> None:
        self.root = Path(root)
        self.identity = identity
        self.attempt_index = attempt_index
        lane = (
            self.root
            / _safe_component(identity.model_alias)
            / _safe_component(identity.task_id)
            / f"trial-{identity.trial_index:03d}-{identity.config_sha256[:12]}"
        )
        self.frames_path = lane / "turn_frames.jsonl"
        self.provider_events_path = lane / "provider_attempts.jsonl"
        self.seal_path = lane / "completed.json"
        self.unsafe_resume_marker_path = lane / "unsafe_resume_blocked.json"
        self.lock_path = lane / ".journal.lock"
        self.snapshots_root = lane / "snapshots"
        self.compact_snapshots = bool(compact_snapshots)
        # Full hash-chain verification stays mandatory for readers, but an
        # append must not re-read the entire JSONL after every native call.
        # Remember only a tail that this object has already verified while it
        # held the lane lock; a size/inode/mtime change invalidates the cache.
        self._verified_tail_cache: dict[
            tuple[str, str],
            tuple[int, int, int, int, int, str],
        ] = {}

    def _store_snapshot(self, value: Any) -> dict[str, Any]:
        """Store one canonical JSON value once and return a small hash-bound ref.

        the benchmark world snapshots and cumulative trajectory objects can be
        tens of MiB.  Embedding the same value in every parallel tool-result
        frame made the append-only journal grow quadratically.  The frame still
        fsyncs atomically and remains hash chained; only its bulky immutable
        value moves to a content-addressed, gzip-compressed side blob.
        """

        raw = canonical_json(value).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        path = self.snapshots_root / digest[:2] / f"{digest}.json.gz"
        compressed = gzip.compress(raw, compresslevel=1, mtime=0)
        if not path.exists():
            try:
                _write_once(path, compressed)
            except FileExistsError:
                # Another writer for the same lane/value won the link race.
                pass
        try:
            observed = gzip.decompress(path.read_bytes())
        except (OSError, EOFError) as exc:
            raise JournalIntegrityError(f"invalid snapshot blob: {path}") from exc
        if hashlib.sha256(observed).hexdigest() != digest or observed != raw:
            raise JournalIntegrityError(f"snapshot blob hash/content mismatch: {path}")
        return {
            "schema_version": SNAPSHOT_REF_SCHEMA,
            "sha256": digest,
            "uncompressed_bytes": len(raw),
        }

    def _load_snapshot(self, reference: Any) -> Any:
        if (
            not isinstance(reference, dict)
            or reference.get("schema_version") != SNAPSHOT_REF_SCHEMA
            or not re.fullmatch(r"[0-9a-f]{64}", str(reference.get("sha256") or ""))
        ):
            raise JournalIntegrityError("invalid snapshot reference")
        digest = str(reference["sha256"])
        path = self.snapshots_root / digest[:2] / f"{digest}.json.gz"
        try:
            raw = gzip.decompress(path.read_bytes())
        except (OSError, EOFError) as exc:
            raise JournalIntegrityError(f"missing/invalid snapshot blob: {path}") from exc
        if (
            hashlib.sha256(raw).hexdigest() != digest
            or len(raw) != int(reference.get("uncompressed_bytes", -1))
        ):
            raise JournalIntegrityError(f"snapshot blob integrity mismatch: {path}")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise JournalIntegrityError(f"snapshot blob is not canonical JSON: {path}") from exc

    def _store_trace(self, trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Store individual cumulative-trace entries.  A later turn then adds
        # only one new blob and a short list of refs instead of rewriting the
        # entire 20+ MiB trace once per frame.
        return [self._store_snapshot(item) for item in trace]

    def _load_trace(self, references: Any) -> list[dict[str, Any]]:
        if not isinstance(references, list):
            raise JournalIntegrityError("trace snapshot references must be a list")
        values = [self._load_snapshot(item) for item in references]
        if not all(isinstance(item, dict) for item in values):
            raise JournalIntegrityError("trace snapshot entry is not an object")
        return values

    def compact_tool_result_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Replace duplicated recovery snapshots with immutable blob refs."""

        result = copy.deepcopy(dict(payload))
        if not self.compact_snapshots:
            return result
        state = result.pop("state_after", None)
        trace = result.pop("trace_after", None)
        if isinstance(state, dict):
            result["state_after_ref"] = self._store_snapshot(state)
        if isinstance(trace, list):
            result["trace_after_refs"] = self._store_trace(trace)
        return result

    @contextmanager
    def _lane_lock(self) -> Iterator[None]:
        """Serialize frame/provider appends and the completion seal.

        A lock on an individual JSONL file is insufficient because completion
        must be atomic with respect to *both* journals.  The lane lock also
        prevents a provider event from racing the immutable completion seal.
        """

        self.lock_path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        lock_was_absent = not self.lock_path.exists()
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o640)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            if lock_was_absent:
                _fsync_directory(self.lock_path.parent)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _expected_metadata(self, *, attempt_index: int | None = None) -> dict[str, Any]:
        return self.identity.metadata(
            attempt_index=self.attempt_index if attempt_index is None else attempt_index
        )

    def _load_hash_chain(
        self,
        path: Path,
        *,
        schema: str,
        metadata_required: bool,
    ) -> list[dict[str, Any]]:
        actual_path = resolve_read_path(path)
        if not actual_path.exists():
            return []
        stat_before = actual_path.stat()
        rows: list[dict[str, Any]] = []
        previous = GENESIS_HASH
        last_line_had_newline = True
        with open_binary(path) as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                last_line_had_newline = raw_line.endswith(b"\n")
                if not raw_line.strip():
                    continue
                try:
                    row = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise JournalIntegrityError(
                        f"invalid JSON frame at {actual_path}:{line_number}: {exc}"
                    ) from exc
                if not isinstance(row, dict) or row.get("schema_version") != schema:
                    raise JournalIntegrityError(
                        f"unexpected frame schema at {actual_path}:{line_number}"
                    )
                supplied_hash = row.get("frame_sha256")
                body = dict(row)
                body.pop("frame_sha256", None)
                expected_hash = sha256_json(body)
                if supplied_hash != expected_hash:
                    raise JournalIntegrityError(
                        f"frame hash mismatch at {actual_path}:{line_number}"
                    )
                if row.get("previous_frame_sha256") != previous:
                    raise JournalIntegrityError(
                        f"hash-chain break at {actual_path}:{line_number}"
                    )
                if row.get("sequence") != len(rows):
                    raise JournalIntegrityError(
                        f"non-contiguous sequence at {actual_path}:{line_number}"
                    )
                if metadata_required:
                    metadata = row.get("metadata")
                    if not isinstance(metadata, dict):
                        raise JournalIntegrityError(
                            f"missing frame metadata at {actual_path}:{line_number}"
                        )
                    expected = self.identity.metadata(
                        attempt_index=int(metadata.get("attempt_index", -1))
                    )
                    if metadata != expected:
                        raise JournalIntegrityError(
                            f"identity/config mismatch at {actual_path}:{line_number}"
                        )
                previous = str(supplied_hash)
                rows.append(row)
        stat_after = actual_path.stat()
        if (
            stat_before.st_dev,
            stat_before.st_ino,
            stat_before.st_size,
            stat_before.st_mtime_ns,
        ) != (
            stat_after.st_dev,
            stat_after.st_ino,
            stat_after.st_size,
            stat_after.st_mtime_ns,
        ):
            raise JournalIntegrityError(
                f"journal changed while validating: {actual_path}"
            )
        if stat_after.st_size and not last_line_had_newline:
            raise JournalIntegrityError(f"truncated journal tail: {actual_path}")
        self._verified_tail_cache[(str(actual_path.resolve()), schema)] = (
            stat_after.st_dev,
            stat_after.st_ino,
            stat_after.st_size,
            stat_after.st_mtime_ns,
            len(rows),
            previous,
        )
        return rows

    def frames(self) -> list[dict[str, Any]]:
        return self._load_hash_chain(
            self.frames_path,
            schema=FRAME_SCHEMA,
            metadata_required=True,
        )

    def provider_events(self) -> list[dict[str, Any]]:
        return self._load_hash_chain(
            self.provider_events_path,
            schema=PROVIDER_EVENT_SCHEMA,
            metadata_required=True,
        )

    def _append_hash_chained(
        self,
        path: Path,
        *,
        schema: str,
        row: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self._lane_lock():
            if self.seal_path.exists():
                raise JournalSealedError(
                    f"trajectory is already completed: {self.seal_path}"
                )
            if compressed_path(path).exists():
                raise JournalIntegrityError(
                    "compressed completed journal is read-only and cannot be appended: "
                    f"{compressed_path(path)}"
                )
            path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            path_was_absent = not path.exists()
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o640)
            try:
                stat = os.fstat(fd)
                if stat.st_size:
                    os.lseek(fd, -1, os.SEEK_END)
                    if os.read(fd, 1) != b"\n":
                        raise JournalIntegrityError(
                            f"truncated journal tail: {path}"
                        )
                cache_key = (str(path.resolve()), schema)
                cached = self._verified_tail_cache.get(cache_key)
                if cached is not None and cached[:4] == (
                    stat.st_dev,
                    stat.st_ino,
                    stat.st_size,
                    stat.st_mtime_ns,
                ):
                    sequence = cached[4]
                    previous = cached[5]
                else:
                    existing = self._load_hash_chain(
                        path,
                        schema=schema,
                        metadata_required=True,
                    )
                    sequence = len(existing)
                    previous = (
                        existing[-1]["frame_sha256"]
                        if existing
                        else GENESIS_HASH
                    )
                body = {
                    "schema_version": schema,
                    "sequence": sequence,
                    "previous_frame_sha256": previous,
                    **copy.deepcopy(dict(row)),
                }
                body["frame_sha256"] = sha256_json(body)
                payload = (canonical_json(body) + "\n").encode("utf-8")
                os.lseek(fd, 0, os.SEEK_END)
                view = memoryview(payload)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError(
                            f"short journal append: {len(payload) - len(view)}/"
                            f"{len(payload)}"
                        )
                    view = view[written:]
                os.fsync(fd)
                appended_stat = os.fstat(fd)
                self._verified_tail_cache[cache_key] = (
                    appended_stat.st_dev,
                    appended_stat.st_ino,
                    appended_stat.st_size,
                    appended_stat.st_mtime_ns,
                    sequence + 1,
                    str(body["frame_sha256"]),
                )
                if path_was_absent:
                    _fsync_directory(path.parent)
                return body
            finally:
                os.close(fd)

    def _append_frame(
        self,
        frame_type: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        if frame_type not in {
            "attempt_started",
            "assistant_message",
            "tool_call",
            "tool_result",
            "scenario_boundary",
            "evaluator_outcome",
            "turn_complete",
        }:
            raise ValueError(f"unsupported turn frame type: {frame_type}")
        return self._append_hash_chained(
            self.frames_path,
            schema=FRAME_SCHEMA,
            row={
                "metadata": self._expected_metadata(),
                "frame_type": frame_type,
                "payload": copy.deepcopy(dict(payload)),
            },
        )

    def append_frame(
        self,
        frame_type: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        if frame_type not in {
            "assistant_message",
            "tool_call",
            "tool_result",
            "scenario_boundary",
            "evaluator_outcome",
        }:
            raise ValueError(
                "attempt_started/turn_complete must use lifecycle methods"
            )
        return self._append_frame(frame_type, payload)

    def append_provider_event(
        self,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        if event_type not in PROVIDER_EVENT_TYPES:
            raise ValueError(f"unsupported provider event type: {event_type}")
        return self._append_hash_chained(
            self.provider_events_path,
            schema=PROVIDER_EVENT_SCHEMA,
            row={
                "metadata": self._expected_metadata(),
                "event_type": event_type,
                "payload": copy.deepcopy(dict(payload)),
            },
        )

    def start_attempt(
        self,
        *,
        state: Mapping[str, Any],
        trace: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        resumed_from_frame_sha256: str | None = None,
    ) -> dict[str, Any]:
        existing = self.frames()
        if not existing:
            if resumed_from_frame_sha256 is not None:
                raise JournalIntegrityError(
                    "initial attempt cannot claim a resume frame"
                )
        else:
            boundary = self.resume_boundary()
            if (
                boundary is None
                or resumed_from_frame_sha256 != boundary.last_frame_sha256
            ):
                raise UnsafeResumeError(
                    "new attempt must bind the exact verified resume boundary"
                )
            highest_attempt = max(
                int(frame["metadata"]["attempt_index"])
                for frame in existing
            )
            if self.attempt_index <= highest_attempt:
                raise JournalIntegrityError(
                    "resumed attempt index must increase monotonically"
                )
        payload: dict[str, Any] = {
            "state_sha256": sha256_json(state),
            "trace_sha256": sha256_json(trace),
            "messages_sha256": sha256_json(messages),
            "resumed_from_frame_sha256": resumed_from_frame_sha256,
        }
        if self.compact_snapshots:
            payload.update(
                {
                    "state_ref": self._store_snapshot(dict(state)),
                    "trace_refs": self._store_trace(trace),
                    # A resumed attempt needs one exact history base.  Normal
                    # turns reconstruct subsequent messages from their atomic
                    # assistant/tool frames and never rewrite this list.
                    "messages_ref": self._store_snapshot(messages),
                }
            )
        else:
            payload.update(
                {
                    "state": copy.deepcopy(dict(state)),
                    "trace": copy.deepcopy(trace),
                    "messages": copy.deepcopy(messages),
                }
            )
        return self._append_frame("attempt_started", payload)

    def complete_turn(
        self,
        *,
        step: int,
        state: Mapping[str, Any],
        trace: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        terminal: bool,
        safe_resume: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "step": step,
            "safe_resume": bool(safe_resume),
            "terminal": bool(terminal),
            "state_sha256": sha256_json(state),
            "trace_sha256": sha256_json(trace),
            "messages_sha256": sha256_json(messages),
            "message_count": len(messages),
        }
        if self.compact_snapshots:
            payload.update(
                {
                    "state_ref": self._store_snapshot(dict(state)),
                    "trace_refs": self._store_trace(trace),
                    "messages_reconstruct_from_frames": True,
                }
            )
        else:
            payload.update(
                {
                    "state": copy.deepcopy(dict(state)),
                    "trace": copy.deepcopy(trace),
                    "messages": copy.deepcopy(messages),
                }
            )
        return self._append_frame("turn_complete", payload)

    def _state_from_payload(self, payload: Mapping[str, Any], *, suffix: str = "") -> dict[str, Any]:
        inline_key = f"state{suffix}"
        ref_key = f"state{suffix}_ref"
        value = payload.get(inline_key)
        if value is None and ref_key in payload:
            value = self._load_snapshot(payload[ref_key])
        if not isinstance(value, dict):
            raise JournalIntegrityError(f"snapshot payload lacks {inline_key}")
        if payload.get(f"state{suffix}_sha256") != sha256_json(value):
            raise JournalIntegrityError(f"{inline_key} snapshot hash mismatch")
        return value

    def _trace_from_payload(self, payload: Mapping[str, Any], *, suffix: str = "") -> list[dict[str, Any]]:
        inline_key = f"trace{suffix}"
        refs_key = f"trace{suffix}_refs"
        value = payload.get(inline_key)
        if value is None and refs_key in payload:
            value = self._load_trace(payload[refs_key])
        if not isinstance(value, list):
            raise JournalIntegrityError(f"snapshot payload lacks {inline_key}")
        expected = payload.get(f"trace{suffix}_sha256")
        if expected is not None and expected != sha256_json(value):
            raise JournalIntegrityError(f"{inline_key} snapshot hash mismatch")
        return value

    def _messages_from_boundary_frames(
        self,
        frames: list[dict[str, Any]],
        target: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        payload = target.get("payload") if isinstance(target.get("payload"), dict) else {}
        inline = payload.get("messages")
        if isinstance(inline, list):
            return copy.deepcopy(inline)
        if payload.get("messages_reconstruct_from_frames") is not True:
            raise JournalIntegrityError("boundary frame lacks complete messages")
        target_sequence = int(target.get("sequence", -1))
        attempt_indices = [
            index
            for index, frame in enumerate(frames)
            if int(frame.get("sequence", -1)) <= target_sequence
            and frame.get("frame_type") == "attempt_started"
        ]
        if not attempt_indices:
            raise JournalIntegrityError("compact boundary lacks attempt base")
        base_index = attempt_indices[-1]
        base_payload = frames[base_index].get("payload", {})
        messages = base_payload.get("messages")
        if messages is None and "messages_ref" in base_payload:
            messages = self._load_snapshot(base_payload["messages_ref"])
        if not isinstance(messages, list):
            raise JournalIntegrityError("compact attempt base lacks messages")
        rebuilt = copy.deepcopy(messages)
        for frame in frames[base_index + 1:]:
            if int(frame.get("sequence", -1)) > target_sequence:
                break
            frame_payload = frame.get("payload", {})
            if frame.get("frame_type") == "assistant_message":
                message = frame_payload.get("message")
                if not isinstance(message, dict):
                    raise JournalIntegrityError("assistant frame lacks exact message")
                rebuilt.append(copy.deepcopy(message))
            elif frame.get("frame_type") == "tool_result":
                message = frame_payload.get("tool_message")
                if not isinstance(message, dict):
                    raise JournalIntegrityError("tool-result frame lacks tool message")
                rebuilt.append(copy.deepcopy(message))
        if (
            len(rebuilt) != int(payload.get("message_count", -1))
            or payload.get("messages_sha256") != sha256_json(rebuilt)
        ):
            # Upstream may restart a rollout branch inside one environment
            # attempt.  In that case the current official trace prompt can be
            # shorter than the previous turn and the append-only projection
            # above intentionally does not match.  Recover only when the
            # source-bound trace prompt/current completion plus the atomic
            # tool-result frames reproduce the frozen target hash exactly.
            trace = self._trace_from_payload(payload)
            if not trace or not isinstance(trace[-1], dict):
                raise JournalIntegrityError("reconstructed boundary messages mismatch")
            current = trace[-1]
            prompt = current.get("prompt")
            completion = current.get("completion")
            if not isinstance(prompt, list) or not isinstance(completion, list):
                raise JournalIntegrityError("reconstructed boundary messages mismatch")
            matching_assistant_indices = [
                index
                for index, frame in enumerate(frames)
                if frame.get("frame_type") == "assistant_message"
                and completion == [frame.get("payload", {}).get("message")]
            ]
            if not matching_assistant_indices:
                raise JournalIntegrityError("trace completion mismatches assistant frame")
            assistant_index = matching_assistant_indices[-1]
            branch = copy.deepcopy(prompt) + copy.deepcopy(completion)
            expected_call_ids = [
                str(call.get("id") or "")
                for message in completion
                if isinstance(message, dict)
                for call in (message.get("tool_calls") or [])
                if isinstance(call, dict)
            ]
            if any(not value for value in expected_call_ids) or len(set(expected_call_ids)) != len(
                expected_call_ids
            ):
                raise JournalIntegrityError("trace completion has invalid tool-call identity")
            relevant_results: dict[str, dict[str, Any]] = {}
            relevant_order: list[str] = []
            for frame in frames[assistant_index + 1:]:
                if frame.get("frame_type") != "tool_result":
                    continue
                frame_payload = frame.get("payload", {})
                message = frame_payload.get("tool_message")
                call_id = str(
                    frame_payload.get("tool_call_id")
                    or (message.get("tool_call_id") if isinstance(message, dict) else "")
                    or ""
                )
                if call_id not in expected_call_ids:
                    # Parallel upstream branch recovery can interleave frames
                    # from an abandoned assistant message.  Those tool results
                    # are still retained in the append-only journal, but they
                    # are not part of this trace-bound official message list.
                    continue
                if not isinstance(message, dict):
                    raise JournalIntegrityError("tool-result frame lacks tool message")
                if call_id in relevant_results:
                    raise JournalIntegrityError("duplicate tool result for trace completion")
                relevant_results[call_id] = copy.deepcopy(message)
                relevant_order.append(call_id)
            if set(relevant_results) != set(expected_call_ids):
                raise JournalIntegrityError("trace completion lacks a complete tool-result round")
            # Preserve the exact official message order captured by the atomic
            # frames.  The final frozen message hash below remains authoritative.
            branch.extend(relevant_results[call_id] for call_id in relevant_order)
            if (
                len(branch) != int(payload.get("message_count", -1))
                or payload.get("messages_sha256") != sha256_json(branch)
            ):
                raise JournalIntegrityError("reconstructed boundary messages mismatch")
            rebuilt = branch
        return rebuilt

    def _boundary_from_frame(
        self,
        frame: Mapping[str, Any],
        *,
        source: str,
        frames: list[dict[str, Any]],
    ) -> ResumeBoundary:
        payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}
        state = self._state_from_payload(payload)
        trace = self._trace_from_payload(payload)
        if source == "attempt_started":
            messages = payload.get("messages")
            if messages is None and "messages_ref" in payload:
                messages = self._load_snapshot(payload["messages_ref"])
            if not isinstance(messages, list):
                raise JournalIntegrityError("attempt_started frame lacks complete messages")
            if payload.get("messages_sha256") not in {None, sha256_json(messages)}:
                raise JournalIntegrityError("attempt_started messages hash mismatch")
        else:
            messages = self._messages_from_boundary_frames(frames, frame)
        return ResumeBoundary(
            state=copy.deepcopy(state),
            trace=copy.deepcopy(trace),
            messages=copy.deepcopy(messages),
            source=source,
            last_frame_sha256=str(frame["frame_sha256"]),
            terminal=bool(payload.get("terminal", False)),
        )

    def _side_effect_recovery_is_bound(self, frame: Mapping[str, Any]) -> bool:
        payload = (
            frame.get("payload")
            if isinstance(frame.get("payload"), dict)
            else {}
        )
        if payload.get("side_effect") is not True:
            return True
        recovery = payload.get("environment_recovery")
        if not isinstance(recovery, dict):
            return False
        mode = str(recovery.get("mode") or "")
        if mode == "state_snapshot":
            try:
                state = self._state_from_payload(payload, suffix="_after")
                trace = self._trace_from_payload(payload, suffix="_after")
            except JournalIntegrityError:
                return False
            return recovery.get("state_sha256") == sha256_json(state) and recovery.get(
                "trace_sha256"
            ) == sha256_json(trace)
        if mode == "deterministic_replay":
            receipt = recovery.get("replay_receipt")
            receipt_sha256 = recovery.get("replay_receipt_sha256")
            return (
                isinstance(receipt, dict)
                and receipt.get("deterministic") is True
                and isinstance(receipt_sha256, str)
                and bool(re.fullmatch(r"[0-9a-f]{64}", receipt_sha256))
                and receipt_sha256 == sha256_json(receipt)
            )
        return False

    def resume_boundary(self) -> ResumeBoundary | None:
        if self.seal_path.exists():
            raise JournalSealedError(f"completed trajectory is immutable: {self.seal_path}")
        if self.unsafe_resume_marker_path.exists():
            raise UnsafeResumeError(
                "journal recovery evidence records a truncated side-effecting tool result; "
                f"environment reconciliation is required: {self.unsafe_resume_marker_path}"
            )
        frames = self.frames()
        if not frames:
            return None
        boundary_index = -1
        boundary: ResumeBoundary | None = None
        for index, frame in enumerate(frames):
            if frame.get("frame_type") in {"attempt_started", "turn_complete"}:
                candidate = self._boundary_from_frame(
                    frame,
                    source=str(frame.get("frame_type")),
                    frames=frames[: index + 1],
                )
                if frame.get("frame_type") == "attempt_started" or (
                    frame.get("payload", {}).get("safe_resume") is True
                ):
                    unsafe_effects = [
                        item
                        for item in frames[boundary_index + 1:index]
                        if item.get("frame_type") == "tool_result"
                        and not self._side_effect_recovery_is_bound(item)
                    ]
                    if unsafe_effects:
                        raise UnsafeResumeError(
                            "side-effecting tool result has no environment "
                            "snapshot/deterministic replay proof; reconciliation "
                            "is required"
                        )
                    boundary_index = index
                    boundary = candidate
        if boundary is None:
            raise JournalIntegrityError("journal contains no recoverable initial boundary")
        tail = frames[boundary_index + 1:]
        if not tail:
            return boundary
        if any(
            frame.get("frame_type") == "turn_complete"
            and frame.get("payload", {}).get("safe_resume") is not True
            for frame in tail
        ):
            raise UnsafeResumeError(
                "journal contains an explicitly non-resumable tool round; "
                "environment reconciliation is required"
            )

        assistant_frames = [
            frame for frame in tail if frame.get("frame_type") == "assistant_message"
        ]
        if len(assistant_frames) != 1:
            if any(
                frame.get("frame_type") == "tool_result"
                and frame.get("payload", {}).get("side_effect") is True
                for frame in tail
            ):
                raise UnsafeResumeError(
                    "journal tail has executed side effects but no unique assistant turn; "
                    "environment reconciliation is required"
                )
            return ResumeBoundary(
                **{**boundary.__dict__, "discarded_read_only_tail": True}
            )
        assistant_payload = assistant_frames[0].get("payload", {})
        assistant_message = assistant_payload.get("message")
        if not isinstance(assistant_message, dict):
            raise JournalIntegrityError("assistant frame lacks exact message")
        calls = assistant_message.get("tool_calls") or []
        expected_call_ids = [
            str(call.get("id") or "")
            for call in calls
            if isinstance(call, dict) and call.get("id")
        ]
        if len(expected_call_ids) != len(calls) or len(set(expected_call_ids)) != len(
            expected_call_ids
        ):
            raise JournalIntegrityError(
                "assistant tool calls require unique non-empty IDs"
            )
        call_frames = [
            frame for frame in tail if frame.get("frame_type") == "tool_call"
        ]
        call_ids = [
            str(
                frame.get("payload", {}).get("tool_call_id")
                or (
                    frame.get("payload", {}).get("tool_call", {})
                    if isinstance(
                        frame.get("payload", {}).get("tool_call"), dict
                    )
                    else {}
                ).get("id")
                or ""
            )
            for frame in call_frames
        ]
        result_frames = [
            frame for frame in tail if frame.get("frame_type") == "tool_result"
        ]
        result_ids = [
            str(frame.get("payload", {}).get("tool_call_id") or "")
            for frame in result_frames
        ]
        any_side_effect = any(
            frame.get("payload", {}).get("side_effect") is True
            for frame in result_frames
        )
        if (
            len(set(call_ids)) != len(call_ids)
            or len(set(result_ids)) != len(result_ids)
            or any(not value for value in (*call_ids, *result_ids))
            or not set(call_ids).issubset(set(expected_call_ids))
            or not set(result_ids).issubset(set(expected_call_ids))
        ):
            if any_side_effect:
                raise UnsafeResumeError(
                    "ambiguous side-effecting tool round requires environment "
                    "reconciliation"
                )
            raise JournalIntegrityError(
                "tool call/result frames do not match the assistant call set"
            )
        call_by_id = dict(zip(call_ids, call_frames))
        result_by_id = dict(zip(result_ids, result_frames))
        for call in calls:
            call_id = str(call["id"])
            frame = call_by_id.get(call_id)
            if frame is not None and frame.get("payload", {}).get("tool_call") != call:
                raise JournalIntegrityError(
                    f"tool-call frame diverges from assistant call {call_id}"
                )
        if (
            expected_call_ids
            and all(call_id in call_by_id for call_id in expected_call_ids)
            and all(call_id in result_by_id for call_id in expected_call_ids)
        ):
            ordered_results = sorted(
                (result_by_id[call_id] for call_id in expected_call_ids),
                key=lambda frame: int(frame["sequence"]),
            )
            if any(
                not self._side_effect_recovery_is_bound(frame)
                for frame in ordered_results
            ):
                raise UnsafeResumeError(
                    "completed side-effecting tool round lacks environment "
                    "snapshot/deterministic replay proof"
                )
            last_result = ordered_results[-1]
            last_payload = last_result.get("payload", {})
            state = self._state_from_payload(last_payload, suffix="_after")
            trace = self._trace_from_payload(last_payload, suffix="_after")
            tool_messages = [
                frame.get("payload", {}).get("tool_message")
                for frame in ordered_results
            ]
            if not all(isinstance(message, dict) for message in tool_messages):
                raise JournalIntegrityError("complete tool-result set lacks tool messages")
            return ResumeBoundary(
                state=copy.deepcopy(state),
                trace=copy.deepcopy(trace),
                messages=copy.deepcopy(boundary.messages)
                + [copy.deepcopy(assistant_message)]
                + copy.deepcopy(tool_messages),
                source="reconstructed_complete_tool_result_boundary",
                last_frame_sha256=str(last_result["frame_sha256"]),
                terminal=False,
            )
        if any(
            frame.get("payload", {}).get("side_effect") is True
            for frame in result_frames
        ):
            completed = sorted(result_by_id)
            missing = sorted(set(expected_call_ids) - set(completed))
            raise UnsafeResumeError(
                "partial tool round already executed side effects; blind replay is forbidden; "
                f"completed={completed} missing={missing}"
            )
        return ResumeBoundary(
            **{**boundary.__dict__, "discarded_read_only_tail": True}
        )

    def seal_completed(self, result: Mapping[str, Any]) -> Path:
        with self._lane_lock():
            if self.seal_path.exists():
                raise JournalSealedError(
                    f"completed trajectory is immutable: {self.seal_path}"
                )
            frames = self.frames()
            if not frames or frames[-1].get("frame_type") != "turn_complete":
                raise JournalIntegrityError(
                    "cannot seal without a complete final turn boundary"
                )
            if frames[-1].get("payload", {}).get("terminal") is not True:
                raise JournalIntegrityError("cannot seal a non-terminal turn")
            provider_events = self.provider_events()
            payload = {
                "schema_version": SEAL_SCHEMA,
                "identity": self.identity.metadata(
                    attempt_index=self.attempt_index
                ),
                "final_frame_sha256": frames[-1]["frame_sha256"],
                "frame_count": len(frames),
                "final_provider_event_sha256": (
                    provider_events[-1]["frame_sha256"]
                    if provider_events
                    else GENESIS_HASH
                ),
                "provider_event_count": len(provider_events),
                "result_sha256": sha256_json(result),
                "result": copy.deepcopy(dict(result)),
            }
            payload["seal_sha256"] = sha256_json(payload)
            _write_once(
                self.seal_path,
                (
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
                ).encode("utf-8"),
            )
            for path in (
                self.frames_path,
                self.provider_events_path,
                self.seal_path,
            ):
                if path.exists():
                    path.chmod(0o440)
        return self.seal_path

    def completed_result(self) -> dict[str, Any] | None:
        if not self.seal_path.exists():
            return None
        seal = json.loads(self.seal_path.read_text(encoding="utf-8"))
        if (
            not isinstance(seal, dict)
            or seal.get("schema_version")
            not in {LEGACY_SEAL_SCHEMA, SEAL_SCHEMA}
        ):
            raise JournalIntegrityError("invalid completed seal")
        supplied = seal.get("seal_sha256")
        body = dict(seal)
        body.pop("seal_sha256", None)
        if supplied != sha256_json(body):
            raise JournalIntegrityError("completed seal hash mismatch")
        seal_identity = seal.get("identity")
        if not isinstance(seal_identity, dict):
            raise JournalIntegrityError("completed seal lacks identity/config")
        try:
            sealed_attempt = int(seal_identity.get("attempt_index", -1))
        except (TypeError, ValueError) as exc:
            raise JournalIntegrityError(
                "completed seal has invalid attempt identity"
            ) from exc
        if seal_identity != self.identity.metadata(
            attempt_index=sealed_attempt
        ):
            raise JournalIntegrityError("completed seal identity/config mismatch")
        frames = self.frames()
        if (
            not frames
            or seal.get("frame_count") != len(frames)
            or seal.get("final_frame_sha256")
            != frames[-1].get("frame_sha256")
        ):
            raise JournalIntegrityError("completed seal does not bind current journal tail")
        provider_events = self.provider_events()
        if seal.get("schema_version") == SEAL_SCHEMA:
            final_provider_hash = (
                provider_events[-1]["frame_sha256"]
                if provider_events
                else GENESIS_HASH
            )
            if (
                seal.get("provider_event_count") != len(provider_events)
                or seal.get("final_provider_event_sha256")
                != final_provider_hash
            ):
                raise JournalIntegrityError(
                    "completed seal does not bind provider retry journal"
                )
        result = seal.get("result")
        if not isinstance(result, dict) or seal.get("result_sha256") != sha256_json(result):
            raise JournalIntegrityError("completed result hash mismatch")
        return copy.deepcopy(result)
