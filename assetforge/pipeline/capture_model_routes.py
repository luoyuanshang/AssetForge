"""Approved capture-model routes for new Author/Reviewer requests.

This module is deliberately separate from the historical GPT/model_b fallback
chain.  New work opts in with ``CAPTURE_ONLY=1`` and can select one of
the approved capture model, capture_model_2_max, or capture_model_3_flash as the first route.  No
provider_a or provider_b credential is resolved on this path.
"""
from __future__ import annotations

import copy
import os
from types import SimpleNamespace

NAMES = ("capture_1", "capture_2", "capture_3")
ALIASES = {
    "capture_1": "capture_model_1_flash",
    "capture_2": "capture_model_2_max",
    "capture_3": "capture_model_3_xhigh",
}
MODELS = {
    # The provider retired the dated alias.  Its
    # replacement is the same V4.1 Flash service under its stable name.
    "capture_1": "capture_model_1_flash",
    "capture_2": "capture_model_2_max",
    "capture_3": "capture_model_3_flash",
}
PROVIDERS = {"capture_1": "provider_e", "capture_2": "provider_c", "capture_3": "provider_d"}


def _config(get_model_config, key):
    if key == "capture_1":
        from .release_model_routes import load_route
        raw = load_route("capture_model_1_flash")
        # the author runtime's immutable ModelConfig exposes optional transport fields that
        # the local route JSON omits; fill them explicitly for the same
        # OpenAI-compatible Chat Completions adapter contract.
        defaults = {"api_style": "openai_chat", "reasoning_summary": None,
                    "extra_body": None, "extra_headers": None,
                    "stream_required": True, "azure_api_version": None,
                    "azure_endpoint": None, "api_version": None}
        defaults.update(raw)
        value = SimpleNamespace(**defaults)
        # The verified expiring route is the requested V4.1-Flash wire model.
        value.model_name = MODELS[key]
        value.alias = ALIASES[key]
        value.reasoning_effort = "max"
        # The approved capture endpoint is OpenAI-compatible
        # Chat Completions (with thinking content echoed on tool turns).
        value.api_style = "openai_chat"
        return value
    value = copy.copy(get_model_config(ALIASES[key]))
    object.__setattr__(value, "alias", ALIASES[key])
    object.__setattr__(value, "model_name", MODELS[key])
    # The capture providers expose OpenAI-compatible Chat Completions.  Freeze
    # this explicitly instead of relying on inherited/default style detection;
    # the route below is the only capture route using the Responses API.
    if key in {"capture_2", "capture_3"}:
        object.__setattr__(value, "api_style", "chat_completions")
    return value


def resolve(get_model_config):
    """Return (primary, secondary, fallback) using capture models only."""
    configs = {name: _config(get_model_config, name) for name in NAMES}
    preferred = os.environ.get("CAPTURE_PRIMARY", "capture_1").strip() or "capture_1"
    if preferred not in NAMES:
        raise ValueError("CAPTURE_PRIMARY must be capture_1, capture_2, or capture_3")
    order = [preferred] + [name for name in NAMES if name != preferred]
    return tuple(configs[name] for name in order), tuple(order)


def binding(order, attempts=3):
    # Callers may pass canonical keys or resolved aliases.
    order = [next((name for name, alias in ALIASES.items() if value in (name, alias)), value) for value in order]
    return {
        "policy": "capture_models_only_v1",
        "route_order": [
            {"alias": ALIASES[name], "model": MODELS[name], "provider": PROVIDERS[name],
             "reasoning_effort": "max" if name == "capture_1" else "xhigh",
             "api_style": "openai_chat" if name == "capture_1" else "chat_completions"}
            for name in order
        ],
        "same_route_total_attempts": attempts,
        "forbidden_new_routes": ["provider_a", "provider_b", "model_b1", "model_b2", "model_b3", "model_a1"],
        "priority": "capture_model_1_flash",
    }
