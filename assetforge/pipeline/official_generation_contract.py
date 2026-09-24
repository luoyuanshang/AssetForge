"""Opt-in immutable request and turn-boundary parity for cold official runs.

An unset environment preserves historical runs. This is not a claim that every
state-transport or malformed-tool behavior is identical to the official runner.
"""
from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path

ENV = "PIPELINE__GENERATION_CONTRACT"
CONTRACT = "benchmark-official-request-and-turn-boundary-v1"
TOOL_EXECUTION_CONTRACT = "benchmark-official-request-and-tool-execution-v2"
ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "assetforge/artifacts/official_runtime/api_tools_contract.json"
SCHEMA_SHA256 = "149e0bd9e76ef08bbe63f3bed76d82f4e8e63c7c263f7b9bf6f167a7344a263b"


def validate_contract(value):
    if value not in ("", CONTRACT, TOOL_EXECUTION_CONTRACT):
        raise ValueError("unknown frozen official generation contract")
    return value


def active_contract():
    return validate_contract(os.environ.get(ENV, ""))


def tool_definitions():
    raw = SCHEMA_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SCHEMA_SHA256:
        raise ValueError("frozen official tool schema changed")
    return copy.deepcopy(json.loads(raw)["tools"])


def profile(contract):
    validate_contract(contract)
    if not contract:
        return {"contract": "", "historical_generation_preserved": True, "full_pipeline_parity": False}
    tool_definitions()  # validate before admission, not just store an unchecked hash
    value = {"contract": contract, "official_steps": 50, "temperature": "omitted",
            "parallel_tool_calls": "omitted", "tool_choice": "omitted", "n": 1,
            "tool_schema_sha256": SCHEMA_SHA256, "stop_before_last_response_tool_execution": True,
            "full_pipeline_parity": False, "remaining_scope": "native state transport and malformed-tool parity"}
    if contract == TOOL_EXECUTION_CONTRACT:
        value.update(native_tool_arguments=True, native_tool_error_formatter=True,
                     empty_object_arguments_use_native_defaults=True,
                     remaining_scope="native state transport parity")
    return value


def native_tool_execution(contract):
    return validate_contract(contract) == TOOL_EXECUTION_CONTRACT


def freeze_for_owner(prior_owner):
    contract = validate_contract(prior_owner.get("generation_contract", "")) if prior_owner is not None else active_contract()
    expected = profile(contract)
    if prior_owner is not None and contract and prior_owner.get("generation_profile") != expected:
        raise ValueError("resume generation profile changed")
    return contract, expected


def request_config(config):
    # The official Environment defaults n=1; per-model extra_body may override it
    # in the SDK exactly as it does in the evaluation entry point.
    return replace(config, extra_body={"n": 1, **(config.extra_body or {})})
