"""the benchmark-native tool projection for synthetic workflow worlds.

The official ``toolset=api`` exposes ``api_search``, ``api_fetch`` and
``base64_encode``.  This module gives novel fictional worlds the same public
tool vocabulary without importing benchmark tasks, assertions or answer
values.  The assertion DAG remains inside the scorer/critic.
"""
from __future__ import annotations

import base64
import copy
import json
import re
from urllib.parse import parse_qs, unquote, urlsplit

from .role_surface import capabilities_for_task


API_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "api_search",
        "description": "Search the available REST API documentation before calling an endpoint.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
}

API_FETCH_TOOL = {
    "type": "function",
    "function": {
        "name": "api_fetch",
        "description": (
            "Call one documented REST endpoint. Encode params and body as JSON "
            "strings. The tool returns the documented application JSON "
            "directly, matching the the benchmark api_fetch surface."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "method": {"type": "string"},
                "url": {"type": "string"},
                "params": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["method", "url"],
        },
    },
}

BASE64_TOOL = {
    "type": "function",
    "function": {
        "name": "base64_encode",
        "description": "Base64-encode text when a documented endpoint requires it.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
}


def tools() -> list[dict]:
    return [copy.deepcopy(API_SEARCH_TOOL), copy.deepcopy(API_FETCH_TOOL), copy.deepcopy(BASE64_TOOL)]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def endpoint_catalog(task: dict) -> list[dict]:
    """Compile answer-free endpoint docs from visible app/collection schema."""
    explicit = task.get("api_catalog")
    if explicit is not None:
        if not isinstance(explicit, list) or not explicit:
            raise ValueError("api_catalog must be a non-empty list")
        rows = []
        for row in explicit:
            if not isinstance(row, dict):
                raise ValueError("api_catalog rows must be objects")
            if (
                str(row.get("method") or "").upper()
                not in {"GET", "PATCH", "POST"}
                or not isinstance(row.get("url"), str)
                or not str(row["url"]).startswith("/v1/")
                or row.get("operation")
                not in {"search", "read", "update", "create", "send"}
            ):
                raise ValueError("api_catalog contains an invalid endpoint")
            rows.append(copy.deepcopy(row))
        return rows

    state = task.get("initial_state") if isinstance(task.get("initial_state"), dict) else {}
    capabilities = capabilities_for_task(task)
    runtime_config = (
        task.get("runtime_config")
        if isinstance(task.get("runtime_config"), dict)
        else {}
    )
    path_prefixes = (
        runtime_config.get("path_prefixes")
        if isinstance(runtime_config.get("path_prefixes"), dict)
        else {}
    )
    rows = []
    for app in task.get("allowed_apps") or []:
        collections = state.get(app) if isinstance(state.get(app), dict) else {}
        operations = capabilities.get(app, ())
        for collection in sorted(collections):
            app_prefix = path_prefixes.get(str(app))
            if not isinstance(app_prefix, str) or not app_prefix:
                app_prefix = f"/v1/{_slug(str(app))}"
            base = f"{app_prefix}/{_slug(str(collection))}"
            if "search" in operations:
                rows.append({"method": "GET", "url": base, "operation": "search", "params": "JSON field filters"})
            if "read" in operations:
                rows.append({"method": "GET", "url": base + "/{record_id}", "operation": "read"})
            if "update" in operations:
                rows.append({"method": "PATCH", "url": base + "/{record_id}", "operation": "update", "body": "JSON patch"})
            if "create" in operations:
                rows.append({"method": "POST", "url": base, "operation": "create", "body": "JSON record"})
            if "send" in operations:
                rows.append({"method": "POST", "url": base, "operation": "send", "body": "JSON channel and message"})
    return rows


def api_search(task: dict, *, query: str, top_k: int = 5) -> dict:
    if not isinstance(query, str) or not query.strip():
        return {"results": [], "count": 0}
    top_k = max(1, min(int(top_k), 20))
    tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    ranked = []
    for row in endpoint_catalog(task):
        haystack = json.dumps(row, sort_keys=True).lower()
        score = sum(token in haystack for token in tokens)
        ranked.append((score, row["url"], row))
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]["method"]))
    results = [row for _, _, row in ranked[:top_k]]
    return {"results": results, "count": len(results)}


def _json_object(value: object, *, field: str) -> dict:
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return copy.deepcopy(value)
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a JSON string")
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{field} JSON must be an object")
    return parsed


def api_fetch_action(task: dict, *, method: str, url: str, params: object = None, body: object = None) -> dict:
    """Translate one documented native-shaped REST call into a world action."""
    method = str(method or "").upper()
    parsed = urlsplit(str(url or ""))
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) < 3 or parts[0] != "v1":
        raise ValueError(
            "url must match a documented /v1 application prefix, "
            "collection, and optional record identity"
        )
    allowed_apps = [str(app) for app in task.get("allowed_apps") or []]
    runtime_config = (
        task.get("runtime_config")
        if isinstance(task.get("runtime_config"), dict)
        else {}
    )
    path_prefixes = (
        runtime_config.get("path_prefixes")
        if isinstance(runtime_config.get("path_prefixes"), dict)
        else {}
    )
    prefix_matches: list[tuple[int, str]] = []
    for allowed_app in allowed_apps:
        prefix = path_prefixes.get(allowed_app)
        if not isinstance(prefix, str) or not prefix:
            prefix = f"/v1/{_slug(allowed_app)}"
        prefix_parts = [
            unquote(part)
            for part in urlsplit(prefix).path.split("/")
            if part
        ]
        if parts[: len(prefix_parts)] == prefix_parts:
            prefix_matches.append((len(prefix_parts), allowed_app))
    if prefix_matches:
        longest = max(length for length, _ in prefix_matches)
        matching_apps = [
            app for length, app in prefix_matches if length == longest
        ]
        if len(matching_apps) != 1:
            raise ValueError("url matches multiple application path prefixes")
        app = matching_apps[0]
        remaining_parts = parts[longest:]
    else:
        app = None
        remaining_parts = []
    if app is None:
        raise ValueError("url references an unavailable application")
    if len(remaining_parts) not in {1, 2}:
        raise ValueError(
            "url must include one collection and an optional record identity "
            "after the application path prefix"
        )
    state = task.get("initial_state") if isinstance(task.get("initial_state"), dict) else {}
    collection_by_slug = {_slug(str(name)): str(name) for name in (state.get(app) or {})}
    collection = collection_by_slug.get(remaining_parts[0])
    if collection is None:
        raise ValueError("url references an unavailable collection")
    record_id = remaining_parts[1] if len(remaining_parts) == 2 else ""
    query = _json_object(params, field="params")
    if parsed.query:
        query.update({key: values[-1] for key, values in parse_qs(parsed.query).items()})
    payload = _json_object(body, field="body")
    explicit = task.get("api_catalog")
    descriptor: dict | None = None
    if explicit is not None:
        actual_path = "/" + "/".join(parts)

        def documented_path_matches(row: dict) -> bool:
            template = str(row["url"])
            placeholders = re.findall(r"\{[^{}]+\}", template)
            if placeholders:
                if len(placeholders) != 1:
                    raise ValueError(
                        "documented item endpoint has ambiguous placeholders"
                    )
                prefix, suffix = template.split(placeholders[0], 1)
                return (
                    bool(record_id)
                    and actual_path.startswith(prefix)
                    and actual_path.endswith(suffix)
                    and len(actual_path) > len(prefix) + len(suffix)
                )
            return actual_path == template

        documented_routes = [
            row
            for row in endpoint_catalog(task)
            if str(row["method"]).upper() == method
            and documented_path_matches(row)
        ]
        if len(documented_routes) != 1:
            raise ValueError(
                "method/path does not identify exactly one documented endpoint"
            )
        descriptor = documented_routes[0]
    documented_operation = (
        str(descriptor.get("operation") or "")
        if descriptor is not None
        else ""
    )
    if method == "GET" and record_id:
        action = {
            "app": app,
            "operation": "read",
            "collection": collection,
            "record_id": record_id,
            "query": query,
        }
    elif method == "GET":
        action = {
            "app": app,
            "operation": "search",
            "collection": collection,
            "query": query,
        }
    elif method in {"PATCH", "PUT"} and record_id:
        if not payload:
            raise ValueError("documented update endpoint requires a non-empty body")
        action = {
            "app": app,
            "operation": "update",
            "collection": collection,
            "record_id": record_id,
            "patch": payload,
        }
    elif method == "POST" and (
        documented_operation == "send"
        or (
            descriptor is None
            and {"channel", "message"} <= set(payload)
        )
    ):
        action = {
            "app": app,
            "operation": "send",
            "collection": collection,
            "channel": str(payload["channel"]),
            "message": str(payload["message"]),
        }
    elif method == "POST":
        if not payload:
            raise ValueError("documented create endpoint requires a non-empty body")
        action = {
            "app": app,
            "operation": "create",
            "collection": collection,
            "patch": payload,
        }
    else:
        raise ValueError("method/path combination is not documented")

    if explicit is not None:
        if descriptor is None or descriptor["operation"] != action["operation"]:
            raise ValueError(
                "method/path/operation is not an exact documented endpoint"
            )
        if action["operation"] in {"search", "read"}:
            allowed_params = descriptor.get(
                "params_fields",
                [] if action["operation"] == "read" else None,
            )
            if not isinstance(allowed_params, list) or any(
                not isinstance(name, str) or not name
                for name in allowed_params
            ):
                raise ValueError(
                    "documented read/search endpoint lacks params_fields"
                )
            if set(query) - set(allowed_params):
                raise ValueError(
                    "read/search params contain an undocumented field"
                )
        elif action["operation"] in {"update", "create"}:
            allowed_body = descriptor.get("body_fields")
            required_body = descriptor.get("required_body_fields", [])
            if (
                not isinstance(allowed_body, list)
                or not isinstance(required_body, list)
                or any(
                    not isinstance(name, str) or not name
                    for name in [*allowed_body, *required_body]
                )
                or not set(required_body) <= set(allowed_body)
            ):
                raise ValueError(
                    "documented write endpoint has invalid body field metadata"
                )
            if set(payload) - set(allowed_body):
                raise ValueError(
                    "write body contains an undocumented field"
                )
            if not set(required_body) <= set(payload):
                raise ValueError(
                    "write body is missing a documented required field"
                )
        elif action["operation"] == "send":
            if set(payload) != {"channel", "message"}:
                raise ValueError(
                    "send body must contain exactly channel and message"
                )
    return action


def project_error_code(
    runtime_config: dict | None,
    error_code: str,
) -> str:
    stable_code = re.sub(
        r"[^a-z0-9]+",
        "_",
        str(error_code or "invalid_request").lower(),
    ).strip("_") or "invalid_request"
    condition_aliases = {
        "empty_required_field": "missing_field",
        "invalid_enum_value": "unsupported_value",
        "invalid_create_enum_value": "unsupported_value",
        "invalid_update_enum_value": "unsupported_value",
        "unique_create_conflict": "invalid_request",
        "foreign_key_not_found": "unknown_parent",
        "foreign_key_constraint_failed": "invalid_transition",
        "record_not_found": "unknown_record",
        "invalid_transition_source_state": "invalid_transition",
        "invalid_csv_filter": "invalid_csv",
        "invalid_read_expansion": "unsupported_expansion",
        "unsupported_read_expansion": "unsupported_expansion",
    }
    condition = condition_aliases.get(stable_code, stable_code)
    policy = (
        dict(runtime_config or {}).get("public_error_code_policy", {})
    )
    if isinstance(policy, dict) and policy:
        return str(
            policy.get(condition)
            or policy.get("invalid_request")
            or stable_code
        )
    return stable_code


def api_error_result(
    task: dict,
    *,
    method: str,
    url: str,
    error_code: str,
    message: str | None = None,
) -> dict:
    """Project an argument/route rejection onto the authored public envelope."""

    actual_path = urlsplit(str(url or "")).path
    reason = " ".join(str(message or "").split())
    has_authored_policy = bool(
        dict(task.get("runtime_config") or {}).get(
            "public_error_code_policy"
        )
    )

    def path_matches(template: str) -> bool:
        placeholders = re.findall(r"\{[^{}]+\}", template)
        if not placeholders:
            return actual_path == template
        if len(placeholders) != 1:
            return False
        prefix, suffix = template.split(placeholders[0], 1)
        return (
            actual_path.startswith(prefix)
            and actual_path.endswith(suffix)
            and len(actual_path) > len(prefix) + len(suffix)
        )

    all_path_rows = [
        row
        for row in endpoint_catalog(task)
        if path_matches(str(row.get("url") or ""))
    ]
    if error_code == "invalid_request" and has_authored_policy:
        if "requires a non-empty body" in reason or (
            "missing a documented required field" in reason
        ):
            error_code = "missing_field"
        elif "body contains an undocumented field" in reason:
            error_code = "unknown_field"
        elif "params contain an undocumented field" in reason:
            error_code = "unknown_query_parameter"
        else:
            path_rows = all_path_rows
            method_rows = [
                row
                for row in path_rows
                if str(row.get("method") or "").upper()
                == str(method or "").upper()
            ]
            if not path_rows:
                error_code = "path_not_found"
            elif not method_rows:
                error_code = "method_not_allowed"
    matching = []
    for row in endpoint_catalog(task):
        if str(row.get("method") or "").upper() != str(
            method or ""
        ).upper():
            continue
        if path_matches(str(row.get("url") or "")):
            matching.append(row)
    contract_rows = matching or all_path_rows
    if not contract_rows:
        prefix_rows = [
            row
            for row in endpoint_catalog(task)
            if actual_path.startswith(
                str(row.get("url") or "").split("/{", 1)[0].rstrip("/")
                + "/"
            )
        ]
        contract_rows = sorted(
            prefix_rows,
            key=lambda row: len(str(row.get("url") or "")),
            reverse=True,
        )
    contract = (
        contract_rows[0].get("error_response_contract")
        if contract_rows
        and isinstance(
            contract_rows[0].get("error_response_contract"),
            dict,
        )
        else None
    )
    stable_code = project_error_code(
        task.get("runtime_config"),
        error_code,
    )
    stable_message = " ".join(
        str(message or error_code or "request rejected").split()
    )[:512]
    if isinstance(contract, dict):
        return {
            str(contract["code_field"]): stable_code,
            str(contract["message_field"]): stable_message,
        }
    if has_authored_policy:
        return {"ok": False, "error": stable_code}
    return {"ok": False, "error": stable_message}


def encode_text(text: str) -> str:
    # Match the benchmark's public ``base64_encode`` helper.  Gmail-facing
    # API schemas use base64url, where ``+`` and ``/`` are represented as
    # ``-`` and ``_`` respectively.  Keeping the same tool name while
    # matching this byte-level behavior prevents synthetic native-action
    # traces from teaching an unavailable encoding variant.
    return base64.urlsafe_b64encode(str(text).encode()).decode("ascii")
