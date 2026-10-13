"""Bounded Author, Gate, Reviewer and QA stages with immutable outputs."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .construction_assets import ROOT, immutable_write
from .task_package import compile_task
from .rubric_boundary import validate_rubric

REVIEWER_PROMPT = ROOT / "assetforge/protocols/reviewer.md"


def parse_object(content):
    if not isinstance(content, str):
        raise ValueError("model content must be text")
    text = content.strip()
    fence = chr(96) * 3
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        blocks = re.findall(fence + r"(?:json)?[ \t]*\n(.*?)\n" + fence, text, flags=re.DOTALL)
        if len(blocks) != 1:
            raise ValueError("model must return one unambiguous JSON object") from None
        result = json.loads(blocks[0])
    if not isinstance(result, dict):
        raise ValueError("model must return one JSON object")
    return result


def author_prompt(rubric, descriptions, runtime_description):
    return (
        "Create one original business-automation task. Read the task specification and the complete "
        "asset descriptions before choosing parameters. Use only the supplied assets. The public "
        "instruction is written as a business colleague's request. Asset construction supplies "
        "initial records and terminal-state assertions; add only business state and assertions "
        "that the task needs.\n\nTASK SPECIFICATION\n" + rubric +
        "\n\nAVAILABLE ASSETS\n" + json.dumps(descriptions, ensure_ascii=False) +
        "\n\nAVAILABLE APPLICATION CONTRACT\n" + json.dumps(runtime_description, ensure_ascii=False) +
        "\n\nReturn one JSON object with instruction, assets, extra_initial_state (optional), and "
        "extra_assertions (optional). Each assets entry has id, version, alias, reason, and "
        "parameters. Alias is a unique lowercase identifier. Instruction describes the task; "
        "parameters follow the selected asset's documented contract."
    )


def run_pipeline(*, rubric, library, runtime, author, reviewer, output, task_id,
                 asset_ids=None, attempts=3, seed=1, business_time="2026-01-15T09:00:00Z", resume=False):
    if type(attempts) is not int or not 1 <= attempts <= 20:
        raise ValueError("attempts must be an integer in 1..20")
    validate_rubric(rubric)
    descriptions = library.describe(asset_ids)
    permitted = {entry["id"] for entry in descriptions}
    instructions = author_prompt(rubric, descriptions, runtime.describe())
    review_prompt = REVIEWER_PROMPT.read_text()
    output = Path(output)
    inputs = {
        "task_id": task_id, "rubric_sha256": hashlib.sha256(rubric.encode()).hexdigest(),
        "reviewer_prompt_sha256": hashlib.sha256(review_prompt.encode()).hexdigest(),
        "catalog_sha256": library.sha256, "asset_ids": sorted(permitted), "runtime": runtime.describe(),
        "attempts": attempts, "seed": seed, "business_time": business_time,
    }
    if resume:
        if not output.is_dir() or not (output / "inputs.json").is_file():
            raise ValueError("resume requires an existing bound run")
        if json.loads((output / "inputs.json").read_text()) != inputs:
            raise ValueError("resume inputs differ from the original run")
        previous = output / "result.json"
        if previous.exists():
            completed = json.loads(previous.read_text())
            if completed["status"] in ("accepted", "rejected"):
                if completed["status"] == "accepted":
                    qa = output / "qa.json"
                    if not qa.is_file() or hashlib.sha256(qa.read_bytes()).hexdigest() != completed["qa_sha256"]:
                        raise ValueError("published QA differs from the completed run")
                return completed
            if completed["status"] != "failed":
                raise ValueError("unknown prior run state")
            history = output / "recovery"
            history.mkdir(exist_ok=True)
            previous.rename(history / f"result-{len(list(history.glob('result-*.json'))) + 1:02d}.json")
    else:
        output.mkdir(parents=True, exist_ok=False)
    immutable_write(output / "inputs.json", inputs)
    repair = None
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0}
    cached_calls = 0

    def call(client, stage, attempt, messages):
        nonlocal cached_calls
        event_path = output / "events" / f"{attempt:02d}.{stage}.json"
        if resume and event_path.exists():
            event = json.loads(event_path.read_text())
            if event["messages"] != messages or event["stage"] != stage or event["attempt"] != attempt:
                raise ValueError("cached model event does not match this request")
            response = event["response"]
            cached_calls += 1
        else:
            immutable_write(output / "requests" / f"{attempt:02d}.{stage}.json",
                            {"stage": stage, "attempt": attempt, "messages": messages})
            response = client.chat(messages)
        usage = response.get("usage") or {}
        for key in total_usage:
            alias = "input_tokens" if key == "prompt_tokens" else "output_tokens"
            value = usage.get(key, usage.get(alias, 0))
            if type(value) is int and value >= 0:
                total_usage[key] += value
        event = {"stage": stage, "attempt": attempt, "messages": messages,
                 "response": response, "usage": usage}
        immutable_write(event_path, event)
        choices = response.get("choices") or []
        if len(choices) != 1 or not isinstance(choices[0].get("message"), dict):
            raise ValueError("model response must contain one assistant message")
        if choices[0].get("finish_reason") not in (None, "stop"):
            raise ValueError("model response was incomplete")
        return parse_object(choices[0]["message"].get("content"))

    try:
        for attempt in range(1, attempts + 1):
            request = {"task_id": task_id}
            if repair is not None:
                request["previous_submission"] = repair["candidate"]
                request["changes_needed"] = repair["findings"]
            try:
                candidate = call(author, "author", attempt, [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
                ])
            except (ValueError, json.JSONDecodeError) as exc:
                repair = {"candidate": None, "findings": [{"gate": "response_format", "message": str(exc)}]}
                immutable_write(output / f"attempt-{attempt:02d}" / "gate.json",
                                {"passed": False, "diagnostics": repair["findings"]})
                continue
            selected = candidate.get("assets")
            outside = ({r.get("id") for r in selected if isinstance(r, dict) and isinstance(r.get("id"), str)}
                       - permitted) if isinstance(selected, list) else set()
            if outside:
                gate = {"passed": False, "diagnostics": [{"gate": "asset_selection",
                        "pointer": "/assets", "expected": sorted(permitted), "actual": sorted(map(str, outside))}]}
            else:
                gate = compile_task(candidate, library=library, runtime=runtime, task_id=task_id,
                                    seed=seed, business_time=business_time)
            attempt_root = output / f"attempt-{attempt:02d}"
            immutable_write(attempt_root / "candidate.json", candidate)
            immutable_write(attempt_root / "gate.json", gate)
            if not gate["passed"]:
                repair = {"candidate": candidate, "findings": gate["diagnostics"]}
                continue
            packet = {"rubric": rubric, "task": gate["task"], "composition": gate["composition"],
                      "compilation": {"passed": True, "runtime": gate["runtime"]},
                      "asset_descriptions": descriptions}
            verdict = call(reviewer, "reviewer", attempt, [
                {"role": "system", "content": review_prompt},
                {"role": "user", "content": json.dumps(packet, ensure_ascii=False)},
            ])
            if (verdict.get("decision") not in ("accept", "reject") or
                    not isinstance(verdict.get("defects"), list) or
                    not isinstance(verdict.get("rubric_gaps"), list) or
                    any(not isinstance(item, str) for key in ("defects", "rubric_gaps") for item in verdict[key])):
                raise ValueError("Reviewer must return decision, defects and rubric_gaps")
            if verdict["decision"] == "accept" and verdict["defects"]:
                raise ValueError("Reviewer cannot accept with unresolved defects")
            if verdict["decision"] == "reject" and not verdict["defects"]:
                raise ValueError("Reviewer rejection needs actionable defects")
            immutable_write(attempt_root / "review.json", verdict)
            if verdict["decision"] == "reject":
                repair = {"candidate": candidate, "findings": verdict["defects"]}
                continue
            immutable_write(output / "qa.json", gate["task"])
            result = {"status": "accepted", "task_id": task_id, "attempt": attempt,
                      "qa_path": "qa.json", "usage": total_usage, "reviewer": verdict,
                      "cached_calls": cached_calls,
                      "qa_sha256": hashlib.sha256((output / "qa.json").read_bytes()).hexdigest()}
            immutable_write(output / "result.json", result)
            return result
        result = {"status": "rejected", "task_id": task_id, "attempts": attempts,
                  "last_findings": repair["findings"] if repair else [], "usage": total_usage}
        immutable_write(output / "result.json", result)
        return result
    except Exception as exc:
        immutable_write(output / "result.json", {"status": "failed", "task_id": task_id,
                        "error_type": type(exc).__name__, "message": str(exc), "usage": total_usage})
        raise
