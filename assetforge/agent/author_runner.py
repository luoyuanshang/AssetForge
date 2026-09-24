"""Self-contained Author runner.

The Author stage needs an agent loop that can call tools and hand back a task record.  This
module provides that loop locally so the pipeline runs with nothing but a model endpoint:

* the tool surface is the one the Author Rubric describes -- `search`, `visit`, `code_exec`
  plus the controller-side `inspect_task_contract` and `compile_and_test_task_package`;
* the loop is a plain OpenAI-compatible chat-completions tool-calling loop with a turn budget;
* the compiled task record is what gets returned, and it is validated by the pipeline's own
  compiler rather than by anything here.

Deployments that already have their own agent framework can inject it instead; nothing in this
file is required for the pipeline's semantics.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

DEFAULT_TURNS = int(os.environ.get("ASSETFORGE_AUTHOR_MAX_TURNS", "40"))
DEFAULT_TIMEOUT = float(os.environ.get("ASSETFORGE_TIMEOUT_SECONDS", "3600"))


class ModelEndpoint:
    """A minimal OpenAI-compatible chat-completions client (stdlib only)."""

    def __init__(self, *, base_url=None, api_key=None, model=None, timeout=None):
        self.base_url = (base_url or os.environ.get("ASSETFORGE_API_BASE_URL")
                         or os.environ.get("ASSETFORGE_EVAL_BASE_URL"))
        self.api_key = (api_key or os.environ.get("ASSETFORGE_API_KEY")
                        or os.environ.get("ASSETFORGE_EVAL_KEY"))
        self.model = model or os.environ.get("ASSETFORGE_MODEL")
        self.timeout = float(timeout or DEFAULT_TIMEOUT)
        if not self.base_url:
            raise RuntimeError("no model endpoint: set ASSETFORGE_API_BASE_URL")
        if not self.api_key:
            raise RuntimeError("no model credential: set ASSETFORGE_API_KEY")
        if not self.model:
            raise RuntimeError("no model id: set ASSETFORGE_MODEL")

    def chat(self, messages, tools=None, temperature=0.0):
        url = self.base_url.rstrip("/") + "/chat/completions"
        body = {"model": self.model, "messages": messages, "temperature": temperature}
        if tools:
            body["tools"] = tools
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:400]
            raise RuntimeError(f"model endpoint returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"model endpoint unreachable: {exc.reason}") from exc


def tool_schema(name: str, description: str, properties: dict, required=()) -> dict:
    """OpenAI tool schema for one function."""
    return {"type": "function",
            "function": {"name": name, "description": description,
                         "parameters": {"type": "object", "properties": properties,
                                        "required": list(required)}}}


def run_author(*, system_prompt: str, user_prompt: str, tools: dict[str, Callable],
               tool_defs: list[dict], client: ModelEndpoint | None = None,
               max_turns: int | None = None) -> dict[str, Any]:
    """Drive one Author session and return its trace.

    ``tools`` maps a tool name to a callable taking a dict of arguments and returning a string.
    The loop stops when a tool returns a record (an object with ``__emit__`` set) or the turn
    budget is exhausted.
    """
    client = client or ModelEndpoint()
    max_turns = max_turns or DEFAULT_TURNS
    messages = [{"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}]
    trace, emitted = [], None
    for turn in range(1, max_turns + 1):
        response = client.chat(messages, tools=tool_defs)
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        calls = message.get("tool_calls") or []
        messages.append({"role": "assistant", "content": message.get("content") or "",
                         **({"tool_calls": calls} if calls else {})})
        trace.append({"turn": turn, "tool_calls": [c.get("function", {}).get("name") for c in calls]})
        if not calls:
            break
        for call in calls:
            fn = call.get("function") or {}
            name = fn.get("name")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            handler = tools.get(name)
            if handler is None:
                result = f"unknown tool: {name}"
            else:
                try:
                    result = handler(args)
                except Exception as exc:  # a tool error is information for the model
                    result = f"tool {name} failed: {type(exc).__name__}: {exc}"
            if isinstance(result, dict) and result.get("__emit__"):
                emitted = result["record"]
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                 "content": "accepted"})
                return {"status": "emitted", "record": emitted, "trace": trace,
                        "messages": messages, "turns": turn}
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                             "content": str(result)[:20000]})
    return {"status": "exhausted" if emitted is None else "emitted", "record": emitted,
            "trace": trace, "messages": messages, "turns": max_turns}
