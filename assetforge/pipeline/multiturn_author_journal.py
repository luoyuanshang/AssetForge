"""Convert multi-turn research-agent snapshots into a per-frame, auditable author journal."""
from __future__ import annotations

import copy
import json
import re
from typing import Any, Mapping

from .turn_journal import TurnJournal, sha256_json


_PRIVATE_KEYS = {
    "encrypted_content",
    "thinking_signature",
    "signature",
    "private_reasoning",
}


def _public_message(value: Any) -> Any:
    """Strip protocol-private fields; keep ordinary content, tool calls and provider-visible summaries."""
    if isinstance(value, Mapping):
        return {
            str(key): _public_message(child)
            for key, child in value.items()
            if str(key).lower() not in _PRIVATE_KEYS
        }
    if isinstance(value, list):
        return [_public_message(child) for child in value]
    return copy.deepcopy(value)


def _redact_error(value: Any) -> str:
    text = str(value or "")
    text = re.sub(
        r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)(api[_ -]?key\s*[:=]\s*)[^\s,;]+",
        r"\1[REDACTED]",
        text,
    )
    return text[:32_000]


class MultiturnAuthorJournalBridge:
    """Incrementalise rolling snapshots instead of keeping only the final large JSON.

    `code_exec` is a stateful sandbox tool. The current sandbox wrapper destroys the sandbox
    when the process ends and offers no filesystem snapshot or remount, so any turn containing
    it is explicitly marked `safe_resume=false`; that is safer than blindly replaying shell writes.
    """

    def __init__(self, journal: TurnJournal) -> None:
        self.journal = journal
        self.messages: list[dict[str, Any]] = []
        self.trace: list[dict[str, Any]] = []
        self.started = False
        self.turn_index = 0
        self._tool_names: dict[str, str] = {}
        # Audit trail for provider tool calls whose id/name had to be synthesised
        # (see observe()); an empty list means nothing was substituted.
        self.synthesized_tool_call_ids: list[dict[str, Any]] = []

    def pre_model_call(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        turn_index: int,
    ) -> dict[str, str]:
        public_messages = _public_message(messages)
        if not self.started:
            self.journal.start_attempt(
                state={},
                trace=[],
                messages=public_messages,
            )
            self.messages = copy.deepcopy(public_messages)
            self.started = True
        elif public_messages != self.messages:
            raise RuntimeError("author journal/model message boundary diverged before request")
        tool_names = [
            str((tool.get("function") or {}).get("name") or "")
            for tool in tools
            if isinstance(tool, Mapping)
        ]
        self.journal.append_provider_event(
            "request_started",
            {
                "turn_index": int(turn_index),
                "messages_count": len(public_messages),
                "messages_sha256": sha256_json(public_messages),
                "tool_names": tool_names,
            },
        )
        return {"action": "continue"}

    def provider_trace(self, trace: Mapping[str, Any]) -> None:
        public = {
            str(key): _public_message(value)
            for key, value in trace.items()
            if str(key) not in {"error"}
        }
        if "error" in trace:
            public["error"] = _redact_error(trace.get("error"))
        status = str(trace.get("status") or "")
        self.journal.append_provider_event(
            "request_failed" if status == "error" else "request_succeeded",
            public,
        )

    @staticmethod
    def _tool_call(call: Any) -> dict[str, Any]:
        if isinstance(call, Mapping):
            return _public_message(call)
        if hasattr(call, "model_dump"):
            return _public_message(call.model_dump())
        raise TypeError("tool call must be a mapping or SDK model")

    def observe(self, messages: list[dict[str, Any]]) -> None:
        public_messages = _public_message(messages)
        if not self.started:
            raise RuntimeError("trajectory snapshot arrived before journal attempt start")
        if public_messages[: len(self.messages)] != self.messages:
            raise RuntimeError("rolling trajectory rewrote an already-journaled message")
        appended = public_messages[len(self.messages) :]
        if not appended:
            return

        saw_tool_result = False
        stateful_code_exec = False
        terminal = False
        for message in appended:
            role = str(message.get("role") or "")
            if role == "assistant":
                self.turn_index += 1
                self.journal.append_frame(
                    "assistant_message",
                    {
                        "step": self.turn_index,
                        "message": copy.deepcopy(message),
                        "message_sha256": sha256_json(message),
                    },
                )
                calls = message.get("tool_calls") or []
                for position, raw_call in enumerate(calls):
                    call = self._tool_call(raw_call)
                    call_id = str(call.get("id") or "")
                    function = call.get("function") or {}
                    tool_name = str(function.get("name") or "")
                    if not call_id or not tool_name:
                        # Measured 2026-09-15: the provider occasionally returns a
                        # tool call whose id or function name is absent.  Raising
                        # here aborted the whole item (35% of one review stream in
                        # six minutes), even though the conversation itself is
                        # still replayable.  Synthesise a stable id, keep the name
                        # as reported, and record the substitution so the frame
                        # chain stays auditable instead of silently changing.
                        if not call_id:
                            call_id = "auto-%d-%d" % (self.turn_index, position)
                        if not tool_name:
                            tool_name = "unknown"
                        self.synthesized_tool_call_ids.append(
                            {"step": self.turn_index, "position": position,
                             "tool_call_id": call_id, "tool_name": tool_name}
                        )
                        call = dict(call, id=call_id)
                        if isinstance(function, dict):
                            call["function"] = dict(function, name=tool_name)
                    self._tool_names[call_id] = tool_name
                    self.journal.append_frame(
                        "tool_call",
                        {
                            "step": self.turn_index,
                            "tool_call_id": call_id,
                            "tool_name": tool_name,
                            "tool_call": call,
                        },
                    )
                terminal = not bool(calls)
                self.trace.append(
                    {
                        "step": self.turn_index,
                        "kind": "assistant",
                        "message_sha256": sha256_json(message),
                        "tool_call_count": len(calls),
                    }
                )
            elif role == "tool":
                call_id = str(message.get("tool_call_id") or "")
                tool_name = self._tool_names.get(call_id, "unknown")
                side_effect = tool_name == "code_exec"
                stateful_code_exec = stateful_code_exec or side_effect
                saw_tool_result = True
                self.trace.append(
                    {
                        "step": self.turn_index,
                        "kind": "tool_result",
                        "tool_call_id": call_id,
                        "tool_name": tool_name,
                        "message_sha256": sha256_json(message),
                    }
                )
                self.journal.append_frame(
                    "tool_result",
                    {
                        "step": self.turn_index,
                        "tool_call_id": call_id,
                        "tool_name": tool_name,
                        "side_effect": side_effect,
                        "tool_message": copy.deepcopy(message),
                        "state_after": {},
                        "state_after_sha256": sha256_json({}),
                        "trace_after": copy.deepcopy(self.trace),
                        "trace_after_sha256": sha256_json(self.trace),
                        "environment_recovery": (
                            {"mode": "reconciliation_required"}
                            if side_effect
                            else {"mode": "read_only_replay"}
                        ),
                    },
                )
            else:
                raise RuntimeError(f"unexpected appended trajectory role: {role!r}")
            self.messages.append(copy.deepcopy(message))

        if terminal or saw_tool_result:
            self.journal.complete_turn(
                step=self.turn_index,
                state={},
                trace=self.trace,
                messages=self.messages,
                terminal=terminal,
                safe_resume=not stateful_code_exec,
            )

    def mark_controller_terminal_boundary(self) -> None:
        """Seal intent at an already complete tool-result boundary.

        An accepted author package is itself the canonical model output, so the
        controller may stop without asking for another assistant message.  The
        extra lifecycle frame records that intentional terminal decision while
        preserving the exact messages and tool result that were already fsynced.
        """
        frames = self.journal.frames()
        if not frames or frames[-1].get("frame_type") != "turn_complete":
            raise RuntimeError("author controller terminal requires a complete turn")
        payload = frames[-1].get("payload") or {}
        if payload.get("terminal") is True:
            return
        # Compact journals intentionally omit inline ``messages`` and retain
        # only a cryptographic hash/count plus frame reconstruction metadata.
        # Comparing the absent inline field made every valid compact boundary
        # fail with a false "messages diverged" error.  Validate against the
        # canonical hash in either representation.
        inline_messages = payload.get("messages")
        if isinstance(inline_messages, list):
            matches = inline_messages == self.messages
        else:
            matches = (
                payload.get("messages_reconstruct_from_frames") is True
                and int(payload.get("message_count", -1)) == len(self.messages)
                and payload.get("messages_sha256") == sha256_json(self.messages)
            )
        if not matches:
            raise RuntimeError("author controller terminal messages diverged")
        self.journal.complete_turn(
            step=self.turn_index,
            state={},
            trace=self.trace,
            messages=self.messages,
            terminal=True,
            safe_resume=False,
        )
