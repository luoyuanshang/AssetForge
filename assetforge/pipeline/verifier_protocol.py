"""Explicit verifier-tool protocol used for the first SFT stage."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


class VerifierPhase(str, Enum):
    INSPECT_EVIDENCE = "inspect_evidence"
    CHECK_PRECONDITIONS = "check_preconditions"
    AUTHORIZE_OR_RECOVER = "authorize_or_recover"
    EXECUTE = "execute"
    READBACK = "readback"
    FINALIZE = "finalize"


@dataclass(frozen=True)
class VerifierToolReceipt:
    allowed: bool
    phase: VerifierPhase
    codes: tuple[str, ...]
    checked_assertions: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()
    recovery_hint: str | None = None
    verifier_environment_id: str = ""
    state_snapshot_sha256: str = ""
    action_sha256: str = ""
    policy_actor_id: str = ""
    verifier_actor_id: str = ""
    challenge_nonce: str = ""
    role_separated: bool = True
    verdict_bound: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "phase": self.phase.value,
            "codes": list(self.codes),
            "checked_assertions": list(self.checked_assertions),
            "evidence_ids": list(self.evidence_ids),
            "recovery_hint": self.recovery_hint,
            "verifier_environment_id": self.verifier_environment_id,
            "state_snapshot_sha256": self.state_snapshot_sha256,
            "action_sha256": self.action_sha256,
            "policy_actor_id": self.policy_actor_id,
            "verifier_actor_id": self.verifier_actor_id,
            "challenge_nonce": self.challenge_nonce,
            "role_separated": self.role_separated,
            "verdict_bound": self.verdict_bound,
        }


def tool_call(name: str, arguments: dict, *, call_id: str) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(
                arguments,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        },
    }


def verifier_tool_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "verify_action",
            "description": "Check entity-bound evidence and postconditions before claiming or committing an action.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phase": {"type": "string", "enum": [phase.value for phase in VerifierPhase]},
                    "action": {"type": "object"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "required_assertions": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["phase", "action", "evidence_ids", "required_assertions"],
                "additionalProperties": False,
            },
        },
    }


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()
