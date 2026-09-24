"""Compile an agent-authored Markdown candidate into a private executable world.

The substantive scenario remains in the source Markdown. A materializer model
may translate its concrete tables and prose into ``agent-runtime-source-v1``;
this module only validates that translation and mechanically derives endpoint
metadata, assertions, effect closure, and source hashes.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .generator import (
    TASK_SCHEMA_VERSION,
    VERIFICATION_SEMANTICS,
    canonical,
    validate_task,
)
from .native_api import endpoint_catalog


RUNTIME_SOURCE_SCHEMA = "agent-authored-runtime-source-v1"
OPERATIONS = ("search", "read", "update", "create", "send")
SEARCH_OPERATORS = (
    "eq",
    "ieq",
    "lt",
    "lte",
    "gt",
    "gte",
    "in_csv",
    "contains",
)
PUBLIC_ERROR_CONDITIONS = {
    "invalid_request",
    "missing_field",
    "unknown_field",
    "unsupported_value",
    "unknown_parent",
    "unknown_incident",
    "unknown_record",
    "invalid_transition",
    "unknown_query_parameter",
    "invalid_cursor",
    "invalid_csv",
    "unsupported_expansion",
    "path_not_found",
    "method_not_allowed",
}
CORE_PUBLIC_ERROR_CONDITIONS = PUBLIC_ERROR_CONDITIONS - {
    "invalid_cursor",
    "invalid_csv",
    "unsupported_expansion",
}


def markdown_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def extract_task_request(candidate_markdown: str) -> str:
    headings = list(
        re.finditer(r"(?im)^(?P<marks>#{1,6})[ \t]+(?P<title>[^\n#].*?)\s*$", candidate_markdown)
    )

    def normalized(match: re.Match[str]) -> str:
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", match.group("title").lower()).strip()

    def task_boundary(title: str) -> bool:
        return (
            ("student" in title and ("request" in title or "task" in title))
            or ("task" in title and ("request" in title or "instruction" in title))
            or ("request" in title and any(word in title for word in ("public", "business", "executor")))
            or "student request" in title
            or "user request" in title
            or "for students" in title
            or "task request" in title
            or "public statement" in title
        )

    def construction_boundary(title: str) -> bool:
        return (
            (
                "environment" in title
                and any(
                    word in title
                    for word in ("construction", "setup", "scoring", "score", "design", "brief")
                )
            )
            or "environment construction" in title
            or "environment setup" in title
            or "private construction" in title
            or ("environment" in title and any(word in title for word in ("grading", "scoring", "design", "description")))
        )

    task_index = next(
        (index for index, match in enumerate(headings) if task_boundary(normalized(match))),
        None,
    )
    construction_index = next(
        (
            index
            for index, match in enumerate(headings)
            if task_index is not None
            and index > task_index
            and construction_boundary(normalized(match))
        ),
        None,
    )
    if task_index is None or construction_index is None:
        raise ValueError(
            "candidate lacks an unambiguous task-request/environment-construction boundary"
        )
    body = candidate_markdown[
        headings[task_index].end() : headings[construction_index].start()
    ].strip()
    if len(body) < 120:
        raise ValueError("student-facing request is too short")
    return body


def extract_student_request(candidate_markdown: str) -> str:
    """Historical compatibility alias; new artifacts use ``task request``."""

    return extract_task_request(candidate_markdown)


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not result:
        raise ValueError("application or collection name has no URL-safe slug")
    return result


def _nonempty_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value.strip()


def _student_api_description(value: Any, *, field: str) -> str:
    """Require ordinary, self-contained documentation on the student surface."""

    text = _nonempty_text(value, field=field)
    lowered = text.casefold()
    construction_markers = (
        "candidate brief",
        "construction brief",
        "private brief",
    )
    if any(marker in lowered for marker in construction_markers) or re.search(
        r"\bfictional\b",
        lowered,
    ):
        raise ValueError(
            f"{field} must be ordinary self-contained API documentation and "
            "must not reference fictional/private candidate construction"
        )
    return text


def _string_list(value: Any, *, field: str, allow_empty: bool = False) -> list[str]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise ValueError(f"{field} must be a unique string list")
    return list(value)


def _response_contract(
    value: Any,
    *,
    operations: list[str],
    field: str,
) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    allowed = {*operations, "error"}
    if set(value) - allowed:
        raise ValueError(f"{field} declares an unsupported operation")
    normalized: dict[str, dict[str, Any]] = {}
    for operation, raw in value.items():
        if not isinstance(raw, Mapping):
            raise ValueError(f"{field}.{operation} must be an object")
        row = dict(raw)
        if operation == "search":
            if set(row) != {"records_field", "next_cursor_field"}:
                raise ValueError(
                    f"{field}.search must declare only records_field and "
                    "next_cursor_field"
                )
            records_field = _nonempty_text(
                row.get("records_field"),
                field=f"{field}.search.records_field",
            )
            next_cursor_field = _nonempty_text(
                row.get("next_cursor_field"),
                field=f"{field}.search.next_cursor_field",
            )
            if records_field == next_cursor_field:
                raise ValueError(
                    f"{field}.search response fields must be distinct"
                )
            normalized[operation] = {
                "records_field": records_field,
                "next_cursor_field": next_cursor_field,
            }
        elif operation == "read":
            if set(row) != {"direct_record"} or row.get(
                "direct_record"
            ) is not True:
                raise ValueError(
                    f"{field}.read must declare direct_record=true only"
                )
            normalized[operation] = {"direct_record": True}
        elif operation in {"create", "update", "send"}:
            if set(row) != {
                "record_field",
                "status_field",
                "event_id_field",
            }:
                raise ValueError(
                    f"{field}.{operation} must declare only record_field, "
                    "status_field, and event_id_field"
                )
            record_field = _nonempty_text(
                row.get("record_field"),
                field=f"{field}.{operation}.record_field",
            )
            status_field = _nonempty_text(
                row.get("status_field"),
                field=f"{field}.{operation}.status_field",
            )
            event_id_field = _nonempty_text(
                row.get("event_id_field"),
                field=f"{field}.{operation}.event_id_field",
            )
            if (
                len({record_field, status_field, event_id_field}) != 3
                or "id" in {record_field, status_field}
            ):
                raise ValueError(
                    f"{field}.{operation} response fields are invalid"
                )
            normalized[operation] = {
                "record_field": record_field,
                "status_field": status_field,
                "event_id_field": event_id_field,
            }
        else:
            if set(row) != {"code_field", "message_field"}:
                raise ValueError(
                    f"{field}.error must declare only code_field and "
                    "message_field"
                )
            code_field = _nonempty_text(
                row.get("code_field"),
                field=f"{field}.error.code_field",
            )
            message_field = _nonempty_text(
                row.get("message_field"),
                field=f"{field}.error.message_field",
            )
            if code_field == message_field:
                raise ValueError(
                    f"{field}.error response fields must be distinct"
                )
            normalized[operation] = {
                "code_field": code_field,
                "message_field": message_field,
            }
    return normalized


def _source_rows(
    source: Mapping[str, Any],
) -> tuple[
    list[str],
    dict[str, list[str]],
    dict[str, dict[str, list[dict[str, Any]]]],
    list[dict[str, Any]],
    dict[str, Any],
    dict[tuple[str, str], dict[str, Any]],
]:
    apps_value = source.get("applications")
    if not isinstance(apps_value, list) or len(apps_value) < 2:
        raise ValueError("runtime source requires at least two applications")
    allowed_apps: list[str] = []
    app_capabilities: dict[str, list[str]] = {}
    initial_state: dict[str, dict[str, list[dict[str, Any]]]] = {}
    catalog: list[dict[str, Any]] = []
    create_sequences: dict[str, dict[str, list[str]]] = {}
    create_id_rules: dict[str, dict[str, list[dict[str, Any]]]] = {}
    identity_fields: dict[str, dict[str, str]] = {}
    search_rules: dict[str, dict[str, dict[str, dict[str, str]]]] = {}
    read_expansions: dict[str, dict[str, list[dict[str, str]]]] = {}
    create_unique_fields: dict[str, dict[str, list[str]]] = {}
    required_create_fields_config: dict[str, dict[str, list[str]]] = {}
    field_enums: dict[str, dict[str, dict[str, list[str]]]] = {}
    create_field_enums: dict[str, dict[str, dict[str, list[str]]]] = {}
    update_field_enums: dict[str, dict[str, dict[str, list[str]]]] = {}
    foreign_keys: dict[str, dict[str, list[dict[str, Any]]]] = {}
    response_contracts: dict[
        str,
        dict[str, dict[str, dict[str, Any]]],
    ] = {}
    path_prefixes: dict[str, str] = {}
    used_path_prefixes: set[str] = set()
    collection_specs: dict[tuple[str, str], dict[str, Any]] = {}
    endpoint_keys: set[tuple[str, str, str]] = set()
    emitted_contract_fields: dict[tuple[str, str], set[str]] = {}
    for emitted in source.get("mutation_emitted_artifacts", []) or []:
        if not isinstance(emitted, Mapping):
            continue
        artifact = emitted.get("artifact")
        if not isinstance(artifact, Mapping):
            continue
        emitted_app = artifact.get("app")
        emitted_collection = artifact.get("collection")
        fields = artifact.get("fields")
        if (
            isinstance(emitted_app, str)
            and emitted_app
            and isinstance(emitted_collection, str)
            and emitted_collection
            and isinstance(fields, Mapping)
        ):
            emitted_contract_fields.setdefault(
                (emitted_app, emitted_collection),
                set(),
            ).update(str(field) for field in fields)

    for app_value in apps_value:
        if not isinstance(app_value, Mapping):
            raise ValueError("application rows must be objects")
        app = _nonempty_text(app_value.get("name"), field="application.name")
        if app in allowed_apps:
            raise ValueError(f"duplicate application: {app}")
        app_description = _student_api_description(
            app_value.get("description"),
            field=f"{app}.description",
        )
        explicit_path_prefix = app_value.get("path_prefix")
        if explicit_path_prefix is None:
            path_prefix = f"/v1/{_slug(app)}"
        else:
            path_prefix = _nonempty_text(
                explicit_path_prefix,
                field=f"{app}.path_prefix",
            )
            if not re.fullmatch(
                r"/v1/[a-z0-9][a-z0-9-]*"
                r"(?:/[a-z0-9][a-z0-9-]*)*",
                path_prefix,
            ):
                raise ValueError(
                    f"{app}.path_prefix must be a complete lowercase "
                    "/v1 application path without a trailing slash"
                )
        if path_prefix in used_path_prefixes:
            raise ValueError(
                f"duplicate application path_prefix: {path_prefix}"
            )
        used_path_prefixes.add(path_prefix)
        path_prefixes[app] = path_prefix
        collections = app_value.get("collections")
        if not isinstance(collections, list) or not collections:
            raise ValueError(f"{app} has no collections")
        allowed_apps.append(app)
        initial_state[app] = {}
        operations_for_app: list[str] = []
        for collection_value in collections:
            if not isinstance(collection_value, Mapping):
                raise ValueError("collection rows must be objects")
            collection = _nonempty_text(
                collection_value.get("name"),
                field=f"{app}.collection.name",
            )
            if collection in initial_state[app]:
                raise ValueError(f"duplicate collection: {app}/{collection}")
            description = _student_api_description(
                collection_value.get("description"),
                field=f"{app}/{collection}.description",
            )
            operations = _string_list(
                collection_value.get("operations"),
                field=f"{app}/{collection}.operations",
            )
            if any(operation not in OPERATIONS for operation in operations):
                raise ValueError(f"{app}/{collection} has unsupported operations")
            normalized_response_contract = _response_contract(
                collection_value.get("response_contract"),
                operations=operations,
                field=f"{app}/{collection}.response_contract",
            )
            if normalized_response_contract:
                response_contracts.setdefault(app, {})[
                    collection
                ] = normalized_response_contract
            records = collection_value.get("records")
            if not isinstance(records, list) or any(
                not isinstance(record, dict) for record in records
            ):
                raise ValueError(f"{app}/{collection}.records must be an object list")
            copied_records = copy.deepcopy(records)
            record_ids = [
                str(record.get("id") or "")
                for record in copied_records
            ]
            if any(not record_id for record_id in record_ids) or len(
                record_ids
            ) != len(set(record_ids)):
                raise ValueError(
                    f"{app}/{collection} records require unique non-empty ids"
                )
            initial_state[app][collection] = copied_records

            all_record_fields = sorted(
                {
                    str(field)
                    for record in copied_records
                    for field in record
                    if str(field) != "id"
                }
            )
            search_fields = _string_list(
                collection_value.get("search_fields", all_record_fields),
                field=f"{app}/{collection}.search_fields",
                allow_empty=True,
            )
            pagination_parameters = _string_list(
                collection_value.get("pagination_parameters", []),
                field=f"{app}/{collection}.pagination_parameters",
                allow_empty=True,
            )
            if (
                set(pagination_parameters) - {"limit", "cursor"}
                or len(pagination_parameters)
                != len(set(pagination_parameters))
                or set(search_fields) & {"limit", "cursor"}
            ):
                raise ValueError(
                    f"{app}/{collection} pagination parameters must be "
                    "distinct from business search fields"
                )
            raw_search_rules = collection_value.get("search_rules", {})
            if not isinstance(raw_search_rules, Mapping):
                raise ValueError(
                    f"{app}/{collection}.search_rules must be an object"
                )
            normalized_search_rules: dict[str, dict[str, str]] = {}
            for parameter, raw_rule in raw_search_rules.items():
                if (
                    not isinstance(parameter, str)
                    or parameter not in search_fields
                    or not isinstance(raw_rule, Mapping)
                ):
                    raise ValueError(
                        f"{app}/{collection} has an invalid search rule"
                    )
                field = _nonempty_text(
                    raw_rule.get("field"),
                    field=f"{app}/{collection}.search_rules.field",
                )
                operator = _nonempty_text(
                    raw_rule.get("operator"),
                    field=f"{app}/{collection}.search_rules.operator",
                )
                if (
                    field not in {"id", *all_record_fields}
                    or operator not in SEARCH_OPERATORS
                ):
                    raise ValueError(
                        f"{app}/{collection} has an unsupported search rule"
                    )
                normalized_search_rules[parameter] = {
                    "field": field,
                    "operator": operator,
                }
            if normalized_search_rules:
                search_rules.setdefault(app, {})[collection] = (
                    normalized_search_rules
                )
            update_fields = _string_list(
                collection_value.get("update_fields", []),
                field=f"{app}/{collection}.update_fields",
                allow_empty=True,
            )
            required_update_fields = _string_list(
                collection_value.get("required_update_fields", []),
                field=f"{app}/{collection}.required_update_fields",
                allow_empty=True,
            )
            if not set(required_update_fields) <= set(update_fields):
                raise ValueError(
                    f"{app}/{collection} required update fields are not allowed"
                )
            create_fields = _string_list(
                collection_value.get("create_fields", []),
                field=f"{app}/{collection}.create_fields",
                allow_empty=True,
            )
            required_create_fields = _string_list(
                collection_value.get("required_create_fields", []),
                field=f"{app}/{collection}.required_create_fields",
                allow_empty=True,
            )
            if not set(required_create_fields) <= set(create_fields):
                raise ValueError(
                    f"{app}/{collection} required create fields are not allowed"
                )
            if "update" in operations and not update_fields:
                raise ValueError(
                    f"{app}/{collection} update endpoint lacks update_fields"
                )
            if "create" in operations and not create_fields:
                raise ValueError(
                    f"{app}/{collection} create endpoint lacks create_fields"
                )
            if required_create_fields:
                required_create_fields_config.setdefault(app, {})[
                    collection
                ] = copy.deepcopy(required_create_fields)
            server_ids = _string_list(
                collection_value.get("server_generated_ids", []),
                field=f"{app}/{collection}.server_generated_ids",
                allow_empty=True,
            )
            if server_ids and not ({"create", "send"} & set(operations)):
                raise ValueError(
                    f"{app}/{collection} declares server IDs without create/send"
                )
            if set(server_ids) & set(record_ids):
                raise ValueError(
                    f"{app}/{collection} server IDs collide with initial records"
                )
            if server_ids:
                create_sequences.setdefault(app, {})[collection] = server_ids
            raw_id_rules = collection_value.get(
                "server_generated_id_rules",
                [],
            )
            if not isinstance(raw_id_rules, list) or any(
                not isinstance(rule, Mapping)
                for rule in raw_id_rules
            ):
                raise ValueError(
                    f"{app}/{collection}.server_generated_id_rules "
                    "must be an object list"
                )
            id_rules: list[dict[str, Any]] = []
            rule_ids: set[str] = set()
            match_signatures: set[str] = set()
            for rule in raw_id_rules:
                generated_id = _nonempty_text(
                    rule.get("id"),
                    field=(
                        f"{app}/{collection}."
                        "server_generated_id_rules.id"
                    ),
                )
                match_fields = rule.get("match_fields")
                if (
                    generated_id not in server_ids
                    or generated_id in rule_ids
                    or not isinstance(match_fields, Mapping)
                    or not match_fields
                    or "id" in match_fields
                    or not set(match_fields) <= set(create_fields)
                ):
                    raise ValueError(
                        f"{app}/{collection} has an invalid keyed "
                        "server ID rule"
                    )
                signature = canonical(match_fields)
                if signature in match_signatures:
                    raise ValueError(
                        f"{app}/{collection} has duplicate keyed ID rules"
                    )
                rule_ids.add(generated_id)
                match_signatures.add(signature)
                id_rules.append({
                    "id": generated_id,
                    "match_fields": copy.deepcopy(dict(match_fields)),
                })
            if id_rules:
                if "create" not in operations or rule_ids != set(server_ids):
                    raise ValueError(
                        f"{app}/{collection} keyed ID rules must cover every "
                        "declared create ID exactly once"
                    )
                create_id_rules.setdefault(app, {})[collection] = id_rules

            unique_fields = _string_list(
                collection_value.get("create_unique_fields", []),
                field=f"{app}/{collection}.create_unique_fields",
                allow_empty=True,
            )
            if not set(unique_fields) <= set(create_fields):
                raise ValueError(
                    f"{app}/{collection} create unique fields are not "
                    "create-body fields"
                )
            if unique_fields:
                create_unique_fields.setdefault(app, {})[
                    collection
                ] = unique_fields

            raw_enums = collection_value.get("field_enums", {})
            if not isinstance(raw_enums, Mapping):
                raise ValueError(
                    f"{app}/{collection}.field_enums must be an object"
                )
            normalized_enums: dict[str, list[str]] = {}
            known_contract_fields = (
                set(all_record_fields)
                | set(update_fields)
                | set(create_fields)
                | emitted_contract_fields.get((app, collection), set())
            )
            for field, values in raw_enums.items():
                if (
                    not isinstance(field, str)
                    or field not in known_contract_fields
                ):
                    raise ValueError(
                        f"{app}/{collection} enum references an "
                        "unsupported field"
                    )
                normalized_enums[field] = _string_list(
                    values,
                    field=f"{app}/{collection}.field_enums.{field}",
                )
            if normalized_enums:
                if any(
                    field in record
                    and record[field] is not None
                    and record[field] not in values
                    for field, values in normalized_enums.items()
                    for record in copied_records
                ):
                    raise ValueError(
                        f"{app}/{collection} initial record violates "
                        "a field enum"
                    )
                field_enums.setdefault(app, {})[
                    collection
                ] = normalized_enums

            raw_create_enums = collection_value.get(
                "create_field_enums",
                {},
            )
            if not isinstance(raw_create_enums, Mapping):
                raise ValueError(
                    f"{app}/{collection}.create_field_enums must be an object"
                )
            normalized_create_enums: dict[str, list[str]] = {}
            for field, values in raw_create_enums.items():
                if (
                    not isinstance(field, str)
                    or field not in create_fields
                ):
                    raise ValueError(
                        f"{app}/{collection} create enum references a "
                        "non-create field"
                    )
                normalized_create_enums[field] = _string_list(
                    values,
                    field=(
                        f"{app}/{collection}."
                        f"create_field_enums.{field}"
                    ),
                )
                if (
                    field in normalized_enums
                    and not set(normalized_create_enums[field])
                    <= set(normalized_enums[field])
                ):
                    raise ValueError(
                        f"{app}/{collection} create enum exceeds the "
                        "stored field domain"
                    )
            if normalized_create_enums:
                if "create" not in operations:
                    raise ValueError(
                        f"{app}/{collection} declares create enums without "
                        "a create endpoint"
                    )
                create_field_enums.setdefault(app, {})[
                    collection
                ] = normalized_create_enums

            raw_update_enums = collection_value.get(
                "update_field_enums",
                {},
            )
            if not isinstance(raw_update_enums, Mapping):
                raise ValueError(
                    f"{app}/{collection}.update_field_enums must be an object"
                )
            normalized_update_enums: dict[str, list[str]] = {}
            for field, values in raw_update_enums.items():
                if (
                    not isinstance(field, str)
                    or field not in update_fields
                ):
                    raise ValueError(
                        f"{app}/{collection} update enum references a "
                        "non-update field"
                    )
                normalized_update_enums[field] = _string_list(
                    values,
                    field=(
                        f"{app}/{collection}."
                        f"update_field_enums.{field}"
                    ),
                )
                if (
                    field in normalized_enums
                    and not set(normalized_update_enums[field])
                    <= set(normalized_enums[field])
                ):
                    raise ValueError(
                        f"{app}/{collection} update enum exceeds the "
                        "stored field domain"
                    )
            if normalized_update_enums:
                if "update" not in operations:
                    raise ValueError(
                        f"{app}/{collection} declares update enums without "
                        "an update endpoint"
                    )
                update_field_enums.setdefault(app, {})[
                    collection
                ] = normalized_update_enums

            raw_foreign_keys = collection_value.get("foreign_keys", [])
            if not isinstance(raw_foreign_keys, list) or any(
                not isinstance(row, Mapping) for row in raw_foreign_keys
            ):
                raise ValueError(
                    f"{app}/{collection}.foreign_keys must be an object list"
                )
            normalized_foreign_keys: list[dict[str, Any]] = []
            for foreign_key in raw_foreign_keys:
                field = _nonempty_text(
                    foreign_key.get("field"),
                    field=f"{app}/{collection}.foreign_keys.field",
                )
                if field not in known_contract_fields:
                    raise ValueError(
                        f"{app}/{collection} foreign key references an "
                        "unsupported field"
                    )
                normalized_foreign_key = {
                    "field": field,
                    "app": _nonempty_text(
                        foreign_key.get("app"),
                        field=(
                            f"{app}/{collection}.foreign_keys.app"
                        ),
                    ),
                    "collection": _nonempty_text(
                        foreign_key.get("collection"),
                        field=(
                            f"{app}/{collection}.foreign_keys.collection"
                        ),
                    ),
                    "target_field": _nonempty_text(
                        foreign_key.get("target_field") or "id",
                        field=(
                            f"{app}/{collection}."
                            "foreign_keys.target_field"
                        ),
                    ),
                }
                if foreign_key.get("role") is not None:
                    normalized_foreign_key["role"] = _nonempty_text(
                        foreign_key.get("role"),
                        field=f"{app}/{collection}.foreign_keys.role",
                    )
                target_required_fields = foreign_key.get(
                    "target_required_fields",
                    {},
                )
                if not isinstance(target_required_fields, Mapping):
                    raise ValueError(
                        f"{app}/{collection} foreign key target requirements "
                        "must be an object"
                    )
                source_to_target = foreign_key.get(
                    "source_to_target_field_matches",
                    {},
                )
                if (
                    not isinstance(source_to_target, Mapping)
                    or any(
                        not isinstance(source_field, str)
                        or source_field not in known_contract_fields
                        or not isinstance(target_field, str)
                        or not target_field
                        for source_field, target_field
                        in source_to_target.items()
                    )
                ):
                    raise ValueError(
                        f"{app}/{collection} foreign key field matches are invalid"
                    )
                if target_required_fields:
                    normalized_foreign_key["target_required_fields"] = (
                        copy.deepcopy(dict(target_required_fields))
                    )
                if source_to_target:
                    normalized_foreign_key[
                        "source_to_target_field_matches"
                    ] = {
                        str(source_field): str(target_field)
                        for source_field, target_field
                        in source_to_target.items()
                    }
                normalized_foreign_keys.append(normalized_foreign_key)
            if len({
                row["field"] for row in normalized_foreign_keys
            }) != len(normalized_foreign_keys):
                raise ValueError(
                    f"{app}/{collection} has duplicate foreign key fields"
                )
            if normalized_foreign_keys:
                foreign_keys.setdefault(app, {})[
                    collection
                ] = normalized_foreign_keys

            explicit_identity_field = collection_value.get(
                "identity_field"
            )
            normalized_identity_field: str | None = None
            if explicit_identity_field is not None:
                normalized_identity_field = _nonempty_text(
                    explicit_identity_field,
                    field=f"{app}/{collection}.identity_field",
                )
                if (
                    normalized_identity_field == "id"
                    or normalized_identity_field
                    not in {
                        *known_contract_fields,
                        *search_fields,
                    }
                ):
                    raise ValueError(
                        f"{app}/{collection} identity_field must name an "
                        "application-native contract field"
                    )
                if copied_records and any(
                    record.get(normalized_identity_field)
                    != record.get("id")
                    for record in copied_records
                ):
                    raise ValueError(
                        f"{app}/{collection} native identity does not match "
                        "the internal row locator"
                    )
                identity_fields.setdefault(app, {})[
                    collection
                ] = normalized_identity_field

            collection_specs[(app, collection)] = {
                "operations": operations,
                "record_ids": record_ids,
                "records": copied_records,
                "record_fields": all_record_fields,
                "search_fields": search_fields,
                "pagination_parameters": pagination_parameters,
                "update_fields": update_fields,
                "required_update_fields": required_update_fields,
                "create_fields": create_fields,
                "required_create_fields": required_create_fields,
                "server_generated_ids": server_ids,
                "server_generated_id_rules": id_rules,
                "search_rules": normalized_search_rules,
                "read_expansions": copy.deepcopy(
                    collection_value.get("read_expansions", [])
                ),
                "create_unique_fields": unique_fields,
                "field_enums": normalized_enums,
                "create_field_enums": normalized_create_enums,
                "update_field_enums": normalized_update_enums,
                "update_prerequisites": copy.deepcopy(
                    collection_value.get("update_prerequisites", [])
                ),
                "foreign_keys": normalized_foreign_keys,
                "identity_field": normalized_identity_field,
                "response_contract": normalized_response_contract,
            }
            base = f"{path_prefix}/{_slug(collection)}"
            identity_candidates = [
                field
                for field in all_record_fields
                if field.endswith("_id")
                and copied_records
                and all(
                    record.get(field) == record.get("id")
                    for record in copied_records
                )
            ]
            identity_placeholder = normalized_identity_field or (
                identity_candidates[0]
                if len(identity_candidates) == 1
                else "record_id"
            )
            if (
                normalized_identity_field is None
                and len(identity_candidates) == 1
            ):
                identity_fields.setdefault(app, {})[
                    collection
                ] = identity_candidates[0]
                collection_specs[(app, collection)][
                    "identity_field"
                ] = identity_candidates[0]
            endpoint_rows = []
            if "search" in operations:
                operator_descriptions = {
                    "eq": lambda field, parameter: (
                        f"record.{field} == supplied {parameter} "
                        "(case-sensitive)"
                    ),
                    "ieq": lambda field, parameter: (
                        f"casefold(record.{field}) == "
                        f"casefold(supplied {parameter})"
                    ),
                    "lt": lambda field, parameter: (
                        f"record.{field} < supplied {parameter}"
                    ),
                    "lte": lambda field, parameter: (
                        f"record.{field} <= supplied {parameter}"
                    ),
                    "gt": lambda field, parameter: (
                        f"record.{field} > supplied {parameter}"
                    ),
                    "gte": lambda field, parameter: (
                        f"record.{field} >= supplied {parameter}"
                    ),
                    "in_csv": lambda field, parameter: (
                        f"record.{field} is one of the comma-separated "
                        f"members supplied in {parameter}"
                    ),
                    "contains": lambda field, parameter: (
                        f"record.{field} contains supplied {parameter}"
                    ),
                }
                rule_descriptions = []
                for parameter in search_fields:
                    rule = normalized_search_rules.get(
                        parameter,
                        {"field": parameter, "operator": "eq"},
                    )
                    is_boolean_field = any(
                        isinstance(record.get(rule["field"]), bool)
                        for record in copied_records
                        if rule["field"] in record
                    )
                    if is_boolean_field and rule["operator"] in {
                        "eq", "in_csv",
                    }:
                        rule_descriptions.append(
                            f"record.{rule['field']} is compared as a boolean; "
                            f"{parameter} accepts a JSON boolean or lowercase "
                            "string true/false"
                        )
                    else:
                        rule_descriptions.append(
                            operator_descriptions[rule["operator"]](
                                rule["field"],
                                parameter,
                            )
                        )
                stored_enum_descriptions = [
                    f"{field}={values}"
                    for field, values in normalized_enums.items()
                ]
                stored_enum_sentence = (
                    "Stored enum domains: "
                    f"{'; '.join(stored_enum_descriptions)}. "
                    if stored_enum_descriptions
                    else ""
                )
                endpoint_rows.append({
                    "method": "GET",
                    "url": base,
                    "operation": "search",
                    "app": app,
                    "collection": collection,
                    "params_fields": [
                        *search_fields,
                        *pagination_parameters,
                    ],
                    "description": (
                        f"{app_description} {description} Search using documented "
                        f"parameters: {', '.join(search_fields) or 'none'}. "
                        "Every listed parameter has the predicate stated "
                        "below; parameters without a custom operator use "
                        "case-sensitive exact equality. "
                        "Different filters are combined with logical AND; "
                        "unknown parameters are rejected. "
                        f"Parameter predicates: "
                        f"{'; '.join(rule_descriptions) or 'all parameters use case-sensitive exact equality'}. "
                        + stored_enum_sentence
                        + (
                            "This endpoint is paginated: the default native "
                            "success payload contains ok, rows, count and an "
                            "optional next_cursor. count is the total number "
                            "of matches before paging; rows is only the current "
                            "page, so clients must follow next_cursor until it "
                            "is absent to obtain the complete result set."
                            if pagination_parameters
                            else
                            "This endpoint is unpaginated and returns every "
                            "matching current record in one response. The "
                            "default native success payload contains exactly "
                            "ok, rows and count, with count equal to len(rows); "
                            "there is no hidden truncation or cursor."
                        )
                        + (
                            " Returned rows are sorted in ascending order by "
                            "the documented native identity "
                            f"`{identity_placeholder}`."
                            if collection_specs[(app, collection)].get(
                                "identity_field"
                            )
                            else
                            " Returned rows use a deterministic ascending "
                            "record order."
                        )
                    ),
                })
            if "read" in operations:
                raw_expansions = collection_specs[
                    (app, collection)
                ]["read_expansions"]
                if not isinstance(raw_expansions, list) or any(
                    not isinstance(expansion, Mapping)
                    for expansion in raw_expansions
                ):
                    raise ValueError(
                        f"{app}/{collection}.read_expansions "
                        "must be an object list"
                    )
                endpoint_rows.append({
                    "method": "GET",
                    "url": base + f"/{{{identity_placeholder}}}",
                    "operation": "read",
                    "app": app,
                    "collection": collection,
                    "params_fields": ["expand"] if raw_expansions else [],
                    "description": (
                        f"{app_description} {description} Fetch one record by "
                        f"native {identity_placeholder}. The default native "
                        "success payload contains exactly ok and row."
                        + (
                            " Supported expand values: "
                            + ", ".join(
                                str(expansion["name"])
                                for expansion in raw_expansions
                            )
                            + ". Multiple values are comma-separated; "
                            "empty or duplicate expansion names are rejected; "
                            "each expansion returns current live immediate "
                            "child records sorted by the child collection's "
                            "native identity."
                            if raw_expansions else ""
                        )
                    ),
                })
            if "update" in operations:
                update_enum_descriptions = [
                    f"{field}={values}"
                    for field, values in normalized_update_enums.items()
                ]
                endpoint_rows.append({
                    "method": "PATCH",
                    "url": base + f"/{{{identity_placeholder}}}",
                    "operation": "update",
                    "app": app,
                    "collection": collection,
                    "body_fields": update_fields,
                    "required_body_fields": required_update_fields,
                    "description": (
                        f"{description} Patch only: "
                        f"{', '.join(update_fields)}. Collection-level enum "
                        f"constraints beyond documented transition rules: "
                        f"{'; '.join(update_enum_descriptions) or 'none'}. "
                        f"Required fields: "
                        f"{', '.join(required_update_fields) or 'none'}. "
                        "A state-equivalent retry is a successful no-op with "
                        "mutation_applied=false and emits no additional side "
                        "effect. The response never contains a changed field."
                    ),
                })
            if "create" in operations:
                create_enum_descriptions = [
                    f"{field}={values}"
                    for field, values in normalized_create_enums.items()
                ]
                foreign_key_descriptions = [
                    _foreign_key_description(row)
                    for row in normalized_foreign_keys
                    if row["field"] in create_fields
                ]
                endpoint_rows.append({
                    "method": "POST",
                    "url": base,
                    "operation": "create",
                    "app": app,
                    "collection": collection,
                    "body_fields": create_fields,
                    "required_body_fields": required_create_fields,
                    "server_generated_id": bool(server_ids),
                    "description": (
                        f"{description} Create one record. Allowed fields: "
                        f"{', '.join(create_fields)}. Required fields: "
                        f"{', '.join(required_create_fields) or 'none'}. "
                        "A required string field must be non-empty. "
                        f"Create-only enum constraints: "
                        f"{'; '.join(create_enum_descriptions) or 'none'}. "
                        f"Active uniqueness key: "
                        f"{', '.join(unique_fields) or 'none'}. "
                        "Undocumented body fields are rejected. "
                        + (
                            "Required relationships must reference existing "
                            "records before any ID allocation: "
                            + "; ".join(foreign_key_descriptions)
                            + ". "
                            if foreign_key_descriptions
                            else ""
                        )
                        + "An exact retry reuses the existing record with "
                        "created=false and emits no additional side effect. "
                        "A request that matches the active uniqueness key but "
                        "differs in any other documented payload field is "
                        "rejected as invalid_request before mutation or ID "
                        "allocation. "
                        "The application payload for a first success returns "
                        "exactly ok, row, created=true and "
                        "mutation_applied=true; an exact retry returns exactly "
                        "ok, row, created=false and mutation_applied=false. "
                        + (
                            "The server generates native "
                            f"{identity_placeholder}."
                            if server_ids else
                            "The request must include any documented client id."
                        )
                    ),
                })
            if "send" in operations:
                endpoint_rows.append({
                    "method": "POST",
                    "url": base,
                    "operation": "send",
                    "app": app,
                    "collection": collection,
                    "description": (
                        f"{description} Send exactly one channel/message payload. "
                        + (
                            "The server generates native "
                            f"{identity_placeholder}."
                            if server_ids else
                            ""
                        )
                    ),
                })
            for row in endpoint_rows:
                operation_response = normalized_response_contract.get(
                    str(row["operation"])
                )
                error_response = normalized_response_contract.get("error")
                if operation_response:
                    row["response_contract"] = copy.deepcopy(
                        operation_response
                    )
                    row["description"] += (
                        " Exact successful response contract: "
                        + canonical(operation_response)
                        + "."
                    )
                if error_response:
                    row["error_response_contract"] = copy.deepcopy(
                        error_response
                    )
                    row["description"] += (
                        " Exact rejected-request response contract: "
                        + canonical(error_response)
                        + "."
                    )
                key = (row["method"], row["url"], row["operation"])
                if key in endpoint_keys:
                    raise ValueError(f"duplicate endpoint descriptor: {key}")
                endpoint_keys.add(key)
                catalog.append(row)
            operations_for_app.extend(operations)
        app_capabilities[app] = [
            operation
            for operation in OPERATIONS
            if operation in set(operations_for_app)
        ]

    for (app, collection), spec in collection_specs.items():
        raw_expansions = spec["read_expansions"]
        normalized_expansions: list[dict[str, str]] = []
        names: set[str] = set()
        for raw_expansion in raw_expansions:
            name = _nonempty_text(
                raw_expansion.get("name"),
                field=f"{app}/{collection}.read_expansions.name",
            )
            child_app = _nonempty_text(
                raw_expansion.get("app") or app,
                field=f"{app}/{collection}.read_expansions.app",
            )
            child_collection = _nonempty_text(
                raw_expansion.get("collection"),
                field=f"{app}/{collection}.read_expansions.collection",
            )
            foreign_key = _nonempty_text(
                raw_expansion.get("foreign_key"),
                field=f"{app}/{collection}.read_expansions.foreign_key",
            )
            child_spec = collection_specs.get(
                (child_app, child_collection)
            )
            child_records = initial_state.get(
                child_app,
                {},
            ).get(child_collection, [])
            child_fields = {
                str(field)
                for record in child_records
                for field in record
            }
            child_fields.update(child_spec["create_fields"])
            if (
                name in names
                or child_spec is None
                or foreign_key not in child_fields
            ):
                raise ValueError(
                    f"{app}/{collection} has an invalid read expansion"
                )
            names.add(name)
            normalized_expansions.append({
                "name": name,
                "app": child_app,
                "collection": child_collection,
                "foreign_key": foreign_key,
            })
        if normalized_expansions:
            read_expansions.setdefault(app, {})[collection] = (
                normalized_expansions
            )

    for app, collections in foreign_keys.items():
        for collection, rows in collections.items():
            for row in rows:
                if (
                    row["app"],
                    row["collection"],
                ) not in collection_specs:
                    raise ValueError(
                        f"{app}/{collection} foreign key target is absent"
                    )
                target_spec = collection_specs[
                    (row["app"], row["collection"])
                ]
                target_fields = {
                    "id",
                    *target_spec["record_fields"],
                    *target_spec["create_fields"],
                    *target_spec["update_fields"],
                }
                target_required_fields = row.get(
                    "target_required_fields",
                    {},
                )
                source_to_target = row.get(
                    "source_to_target_field_matches",
                    {},
                )
                if (
                    row["target_field"] not in target_fields
                    or not set(target_required_fields) <= target_fields
                    or not set(source_to_target.values()) <= target_fields
                ):
                    raise ValueError(
                        f"{app}/{collection} foreign key references an "
                        "unsupported target field"
                    )
                target_rows = initial_state[row["app"]][row["collection"]]
                source_rows = initial_state[app][collection]
                invalid_source = False
                for source_record in source_rows:
                    linked_value = source_record.get(row["field"])
                    if linked_value is None:
                        continue
                    linked_targets = [
                        target
                        for target in target_rows
                        if target.get(row["target_field"])
                        == linked_value
                    ]
                    if not any(
                        all(
                            target.get(field) == expected
                            for field, expected
                            in target_required_fields.items()
                        )
                        and all(
                            source_record.get(source_field)
                            == target.get(target_field)
                            for source_field, target_field
                            in source_to_target.items()
                        )
                        for target in linked_targets
                    ):
                        invalid_source = True
                        break
                if invalid_source:
                    raise ValueError(
                        f"{app}/{collection} initial foreign key is dangling "
                        "or violates its declared target constraints"
                    )

    update_prerequisites: list[dict[str, Any]] = []
    for (app, collection), spec in collection_specs.items():
        raw_guards = spec.get("update_prerequisites", [])
        if not isinstance(raw_guards, list) or any(
            not isinstance(row, Mapping) for row in raw_guards
        ):
            raise ValueError(
                f"{app}/{collection}.update_prerequisites must be an object list"
            )
        for index, raw_guard in enumerate(raw_guards):
            legacy_keys = {
                "patch",
                "related_app",
                "related_collection",
                "source_field_matches",
                "exact_fields",
                "exact_count",
            }
            generic_keys = {
                "patch_required_fields",
                "patch_exact_fields",
                "related_app",
                "related_collection",
                "source_field_matches",
                "patch_field_matches",
                "exact_fields",
                "exact_count",
            }
            if (
                set(raw_guard) != legacy_keys
                and set(raw_guard) != generic_keys
            ):
                raise ValueError(
                    f"{app}/{collection}.update_prerequisites[{index}] has "
                    "unexpected fields"
                )
            legacy = set(raw_guard) == legacy_keys
            patch = raw_guard.get("patch") if legacy else None
            patch_required_fields = (
                []
                if legacy
                else _string_list(
                    raw_guard.get("patch_required_fields"),
                    field=(
                        f"{app}/{collection}.update_prerequisites"
                        ".patch_required_fields"
                    ),
                )
            )
            patch_exact_fields = (
                {}
                if legacy
                else raw_guard.get("patch_exact_fields")
            )
            source_matches = raw_guard.get("source_field_matches")
            patch_matches = (
                {}
                if legacy
                else raw_guard.get("patch_field_matches")
            )
            exact_fields = raw_guard.get("exact_fields")
            exact_count = raw_guard.get("exact_count")
            related_app = _nonempty_text(
                raw_guard.get("related_app"),
                field=f"{app}/{collection}.update_prerequisites.related_app",
            )
            related_collection = _nonempty_text(
                raw_guard.get("related_collection"),
                field=(
                    f"{app}/{collection}.update_prerequisites.related_collection"
                ),
            )
            related_spec = collection_specs.get(
                (related_app, related_collection)
            )
            source_fields = {"id", *spec["record_fields"]}
            related_fields = (
                {
                    "id",
                    *related_spec["record_fields"],
                    *related_spec["create_fields"],
                    *related_spec["update_fields"],
                }
                if related_spec is not None
                else set()
            )
            if (
                "update" not in spec["operations"]
                or (
                    legacy
                    and (
                        not isinstance(patch, Mapping)
                        or not patch
                        or not set(patch) <= set(spec["update_fields"])
                    )
                )
                or (
                    not legacy
                    and (
                        not patch_required_fields
                        or len(set(patch_required_fields))
                        != len(patch_required_fields)
                        or set(patch_required_fields)
                        != set(spec["required_update_fields"])
                        or not isinstance(patch_exact_fields, Mapping)
                        or not set(patch_exact_fields)
                        <= set(patch_required_fields)
                        or not isinstance(patch_matches, Mapping)
                        or not patch_matches
                        or not set(patch_matches) <= related_fields
                        or not set(patch_matches.values())
                        <= set(patch_required_fields)
                    )
                )
                or related_spec is None
                or not isinstance(source_matches, Mapping)
                or not source_matches
                or not isinstance(exact_fields, Mapping)
                or set(source_matches) & set(exact_fields)
                or set(source_matches) & set(patch_matches)
                or set(exact_fields) & set(patch_matches)
                or not set(source_matches) <= related_fields
                or not set(source_matches.values()) <= source_fields
                or not set(exact_fields) <= related_fields
                or type(exact_count) is not int
                or exact_count < 1
            ):
                raise ValueError(
                    f"{app}/{collection}.update_prerequisites[{index}] is invalid"
                )
            update_prerequisites.append({
                "app": app,
                "collection": collection,
                **(
                    {"patch": copy.deepcopy(dict(patch))}
                    if legacy
                    else {
                        "patch_required_fields": patch_required_fields,
                        "patch_exact_fields": copy.deepcopy(
                            dict(patch_exact_fields)
                        ),
                        "patch_field_matches": copy.deepcopy(
                            dict(patch_matches)
                        ),
                    }
                ),
                "related_app": related_app,
                "related_collection": related_collection,
                "source_field_matches": copy.deepcopy(dict(source_matches)),
                "exact_fields": copy.deepcopy(dict(exact_fields)),
                "exact_count": exact_count,
            })

    runtime_config = {
        "create_id_sequences": create_sequences,
        "create_id_rules": create_id_rules,
        "identity_fields": identity_fields,
        "search_rules": search_rules,
        "read_expansions": read_expansions,
        "create_unique_fields": create_unique_fields,
        "required_create_fields": required_create_fields_config,
        "field_enums": field_enums,
        "create_field_enums": create_field_enums,
        "update_field_enums": update_field_enums,
        "foreign_keys": foreign_keys,
        "path_prefixes": path_prefixes,
        "response_contracts": response_contracts,
        "update_prerequisites": update_prerequisites,
    }
    for endpoint in catalog:
        if endpoint.get("operation") != "update":
            continue
        if any(
            row["app"] == endpoint.get("app")
            and row["collection"] == endpoint.get("collection")
            for row in update_prerequisites
        ):
            endpoint["description"] += (
                " Matching updates are accepted only when every documented "
                "related-record prerequisite is satisfied before mutation."
            )
    return (
        allowed_apps,
        app_capabilities,
        initial_state,
        catalog,
        runtime_config,
        collection_specs,
    )


def _foreign_key_description(row: Mapping[str, Any]) -> str:
    """Render every author-declared relationship rule on the native surface."""

    text = (
        f"{row['field']} -> {row['app']}/"
        f"{row['collection']}.{row['target_field']}"
    )
    target_requirements = row.get("target_required_fields", {})
    if target_requirements:
        text += "; target must satisfy " + ", ".join(
            f"{field}={value!r}"
            for field, value in sorted(target_requirements.items())
        )
    source_to_target = row.get("source_to_target_field_matches", {})
    if source_to_target:
        text += "; source/target fields must match: " + ", ".join(
            f"source.{source_field}=target.{target_field}"
            for source_field, target_field in sorted(
                source_to_target.items()
            )
        )
    return text


def _query_value_for_record(record_value: Any, query_value: Any) -> Any:
    if isinstance(record_value, bool):
        if isinstance(query_value, str):
            lowered = query_value.strip().lower()
            if lowered in {"true", "false"}:
                return lowered == "true"
        return query_value
    if isinstance(record_value, (int, float)) and not isinstance(
        record_value,
        bool,
    ):
        try:
            return float(query_value)
        except (TypeError, ValueError):
            return query_value
    return query_value


def _record_matches_search_query(
    record: Mapping[str, Any],
    *,
    query: Mapping[str, Any],
    search_rules: Mapping[str, Mapping[str, str]],
) -> bool:
    """Mirror the native runtime's public search semantics at compile time."""

    for parameter, supplied in query.items():
        rule = search_rules.get(parameter, {})
        field = str(rule.get("field") or parameter)
        operator = str(rule.get("operator") or "eq")
        record_value = record.get(field)
        if operator == "in_csv":
            values = (
                [part.strip() for part in supplied.split(",")]
                if isinstance(supplied, str)
                else list(supplied)
                if isinstance(supplied, list)
                else [supplied]
            )
            if record_value not in [
                _query_value_for_record(record_value, value)
                for value in values
            ]:
                return False
            continue
        if operator == "contains":
            if isinstance(record_value, list):
                if supplied not in record_value:
                    return False
            elif str(supplied) not in str(record_value or ""):
                return False
            continue
        expected = _query_value_for_record(record_value, supplied)
        if operator == "eq" and record_value != expected:
            return False
        if operator == "ieq" and (
            not isinstance(record_value, str)
            or not isinstance(expected, str)
            or record_value.casefold() != expected.casefold()
        ):
            return False
        if operator in {"lt", "lte", "gt", "gte"}:
            try:
                comparisons = {
                    "lt": record_value < expected,
                    "lte": record_value <= expected,
                    "gt": record_value > expected,
                    "gte": record_value >= expected,
                }
            except TypeError:
                return False
            if not comparisons[operator]:
                return False
    return True


def _validate_evidence(
    rows: Any,
    *,
    collection_specs: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError("required_evidence must be an object list")
    result = []
    ids = set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            raise ValueError("required_evidence rows must be objects")
        app = _nonempty_text(row.get("app"), field="evidence.app")
        collection = _nonempty_text(
            row.get("collection"),
            field="evidence.collection",
        )
        spec = collection_specs.get((app, collection))
        if (
            spec is None
            or not {"search", "read"} & set(spec["operations"])
        ):
            raise ValueError("evidence references a non-readable collection")
        record_id = row.get("record_id")
        query = row.get("query")
        if (record_id is None) == (query is None):
            raise ValueError(
                "evidence must declare exactly one of record_id or query"
            )
        value = {
            "id": _nonempty_text(
                row.get("id") or f"evidence-{index:03d}",
                field="evidence.id",
            ),
            "app": app,
            "collection": collection,
        }
        if value["id"] in ids:
            raise ValueError("duplicate evidence id")
        ids.add(value["id"])
        if record_id is not None:
            record_id = _nonempty_text(
                record_id,
                field="evidence.record_id",
            )
            if record_id not in spec["record_ids"]:
                raise ValueError("evidence record_id is absent from initial state")
            value["record_id"] = record_id
            if "read" in spec["operations"]:
                value["oracle_operation"] = "read"
            else:
                target = next(
                    record
                    for record in spec["records"]
                    if str(record.get("id") or "") == record_id
                )
                query: dict[str, Any] = {}
                search_rules = spec["search_rules"]
                for parameter in spec["search_fields"]:
                    rule = search_rules.get(parameter, {
                        "field": parameter,
                        "operator": "eq",
                    })
                    target_field = rule["field"]
                    if (
                        target_field in target
                        and target[target_field] is not None
                    ):
                        query[parameter] = copy.deepcopy(
                            target[target_field]
                        )
                value["oracle_operation"] = "search"
                value["oracle_query"] = query
        else:
            if not isinstance(query, dict):
                raise ValueError("evidence query must be an object")
            if any(
                not isinstance(parameter, str)
                or parameter not in spec["search_fields"]
                for parameter in query
            ):
                raise ValueError(
                    "evidence query must use declared business search fields"
                )
            value["query"] = copy.deepcopy(query)
            value["oracle_operation"] = "search"
            raw_partitions = row.get("acceptable_query_partitions")
            if raw_partitions is not None:
                if (
                    not isinstance(raw_partitions, list)
                    or not raw_partitions
                ):
                    raise ValueError(
                        "evidence acceptable_query_partitions must be a "
                        "non-empty list of query lists"
                    )
                normalized_partitions: list[list[dict[str, Any]]] = []
                for partition in raw_partitions:
                    if (
                        not isinstance(partition, list)
                        or len(partition) < 2
                        or any(
                            not isinstance(member, Mapping)
                            or not member
                            for member in partition
                        )
                    ):
                        raise ValueError(
                            "each evidence query partition must contain at "
                            "least two non-empty query objects"
                        )
                    normalized_members: list[dict[str, Any]] = []
                    member_signatures: set[str] = set()
                    for member in partition:
                        if any(
                            not isinstance(parameter, str)
                            or parameter not in spec["search_fields"]
                            for parameter in member
                        ):
                            raise ValueError(
                                "evidence query partition must use declared "
                                "business search fields"
                            )
                        if not all(
                            member.get(parameter) == expected
                            for parameter, expected in query.items()
                        ) or len(member) <= len(query):
                            raise ValueError(
                                "every evidence partition query must be a "
                                "strict refinement of the base evidence query"
                            )
                        normalized = copy.deepcopy(dict(member))
                        signature = json.dumps(
                            normalized,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        if signature in member_signatures:
                            raise ValueError(
                                "evidence query partition contains a duplicate"
                            )
                        member_signatures.add(signature)
                        normalized_members.append(normalized)
                    normalized_partitions.append(normalized_members)
                value["acceptable_query_partitions"] = (
                    normalized_partitions
                )
            canonical_scope_record_ids = sorted(
                str(record.get("id") or "")
                for record in spec["records"]
                if _record_matches_search_query(
                    record,
                    query=query,
                    search_rules=spec["search_rules"],
                )
                and str(record.get("id") or "")
            )
            # The query text is an oracle construction aid, not the only
            # semantically valid way for a student to inspect the same scope.
            # The scorer may therefore accept one complete broader search
            # whose returned entity set covers this canonical initial scope.
            # Empty canonical scopes remain exact-query-only so that an
            # arbitrary non-empty read cannot satisfy a negative guard.
            if canonical_scope_record_ids:
                value["canonical_scope_record_ids"] = (
                    canonical_scope_record_ids
                )
                value["allow_complete_scope_superset"] = True
        result.append(value)
    return result


def _validate_evidence_effect_dependencies(
    rows: Any,
    *,
    evidence: list[dict[str, Any]],
    effects: list[dict[str, Any]],
) -> dict[str, list[str]]:
    if rows is None:
        rows = []
    if not isinstance(rows, list) or any(
        not isinstance(row, Mapping) for row in rows
    ):
        raise ValueError(
            "evidence_effect_dependencies must be an object list"
        )
    evidence_ids = {row["id"] for row in evidence}
    effect_ids = {row["id"] for row in effects}
    result: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        evidence_id = _nonempty_text(
            row.get("evidence_id"),
            field="evidence_effect_dependencies.evidence_id",
        )
        effect_id = _nonempty_text(
            row.get("effect_id"),
            field="evidence_effect_dependencies.effect_id",
        )
        edge = (evidence_id, effect_id)
        if (
            evidence_id not in evidence_ids
            or effect_id not in effect_ids
            or edge in seen
        ):
            raise ValueError(
                "evidence-effect dependency references an unknown or "
                "duplicate edge"
            )
        seen.add(edge)
        result.setdefault(effect_id, []).append(evidence_id)
    return result


def _validate_effects(
    rows: Any,
    *,
    collection_specs: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("expected_effects must be a non-empty list")
    result = []
    identities = set()
    effect_ids: set[str] = set()
    for effect_index, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            raise ValueError("expected effect rows must be objects")
        effect_id = _nonempty_text(
            row.get("id") or f"effect-{effect_index:03d}",
            field="effect.id",
        )
        if effect_id in effect_ids:
            raise ValueError("duplicate expected effect id")
        effect_ids.add(effect_id)
        operation = _nonempty_text(
            row.get("operation"),
            field="effect.operation",
        )
        app = _nonempty_text(row.get("app"), field="effect.app")
        collection = _nonempty_text(
            row.get("collection"),
            field="effect.collection",
        )
        spec = collection_specs.get((app, collection))
        if spec is None or operation not in spec["operations"]:
            raise ValueError("effect references an unsupported endpoint")
        value: dict[str, Any] = {
            "id": effect_id,
            "operation": operation,
            "app": app,
            "collection": collection,
        }
        if operation == "update":
            record_id = _nonempty_text(
                row.get("record_id"),
                field="effect.record_id",
            )
            patch = row.get("patch")
            contains_fields = row.get("contains_fields", {})
            if (
                record_id not in spec["record_ids"]
                or not isinstance(patch, dict)
                or not isinstance(contains_fields, dict)
                or not (patch or contains_fields)
                or "id" in patch
                or "id" in contains_fields
                or set(patch) & set(contains_fields)
                or (
                    set(patch) | set(contains_fields)
                ) - set(spec["update_fields"])
                or any(
                    not isinstance(tokens, list)
                    or not tokens
                    or any(
                        not isinstance(token, (str, int, float))
                        for token in tokens
                    )
                    for tokens in contains_fields.values()
                )
            ):
                raise ValueError("update effect is not a documented exact patch")
            identity = (operation, app, collection, record_id)
            value.update({
                "record_id": record_id,
                "patch": copy.deepcopy(patch),
                "contains_fields": copy.deepcopy(contains_fields),
            })
        elif operation == "create":
            record_id = row.get("record_id")
            record_id_any_of = row.get("record_id_any_of")
            if (record_id is None) == (record_id_any_of is None):
                raise ValueError(
                    "create effect must declare exactly one of record_id "
                    "or record_id_any_of"
                )
            if record_id is not None:
                record_selector = {
                    "record_id": _nonempty_text(
                        record_id,
                        field="effect.record_id",
                    )
                }
                selector_ids = [record_selector["record_id"]]
            else:
                selector_ids = _string_list(
                    record_id_any_of,
                    field="effect.record_id_any_of",
                )
                if len(selector_ids) < 2 or len(selector_ids) != len(
                    set(selector_ids)
                ):
                    raise ValueError(
                        "effect.record_id_any_of must contain at least two "
                        "unique server-generated IDs"
                    )
                record_selector = {
                    "record_id_any_of": selector_ids,
                }
            patch = row.get("required_patch")
            contains_fields = row.get("contains_fields", {})
            if (
                not set(selector_ids) <= set(spec["server_generated_ids"])
                or not isinstance(patch, dict)
                or not isinstance(contains_fields, dict)
                or not (patch or contains_fields)
                or "id" in patch
                or "id" in contains_fields
                or set(patch) & set(contains_fields)
                or (
                    set(patch) | set(contains_fields)
                ) - set(spec["create_fields"])
                or not set(spec["required_create_fields"]) <= (
                    set(patch) | set(contains_fields)
                )
                or any(
                    not isinstance(tokens, list)
                    or not tokens
                    or any(
                        not isinstance(token, (str, int, float))
                        for token in tokens
                    )
                    for tokens in contains_fields.values()
                )
            ):
                raise ValueError("create effect is not a documented exact record")
            id_rules = spec.get("server_generated_id_rules", [])
            if id_rules:
                matching_rules = [
                    rule
                    for rule in id_rules
                    if rule["id"] in selector_ids
                    and all(
                        patch.get(field) == expected
                        for field, expected in rule["match_fields"].items()
                    )
                ]
                if len(matching_rules) != 1:
                    raise ValueError(
                        "create effect does not preserve one keyed server ID "
                        "relationship"
                    )
            identity = (
                operation,
                app,
                collection,
                tuple(selector_ids),
                canonical(patch),
                canonical(contains_fields),
            )
            value.update({
                **record_selector,
                "required_patch": copy.deepcopy(patch),
                "contains_fields": copy.deepcopy(contains_fields),
            })
        elif operation == "send":
            record_id = _nonempty_text(
                row.get("record_id"),
                field="effect.record_id",
            )
            channel = _nonempty_text(
                row.get("channel"),
                field="effect.channel",
            )
            contains = _string_list(
                row.get("contains_all"),
                field="effect.contains_all",
            )
            if record_id not in spec["server_generated_ids"]:
                raise ValueError(
                    "send effect record_id is not a documented "
                    "server-generated ID"
                )
            identity = (operation, app, collection, record_id)
            value.update({
                "record_id": record_id,
                "channel": channel,
                "contains_all": contains,
            })
        else:
            raise ValueError("effects may only update, create, or send")
        if identity in identities:
            raise ValueError("duplicate expected effect identity")
        identities.add(identity)
        result.append(value)
    return result


def _validate_effect_order_constraints(
    rows: Any,
    *,
    effects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if rows is None:
        return []
    if not isinstance(rows, list) or any(
        not isinstance(row, Mapping) for row in rows
    ):
        raise ValueError("effect_order_constraints must be an object list")
    known = {row["id"] for row in effects}
    result: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        before = _string_list(
            row.get("before_effect_ids"),
            field="effect_order.before_effect_ids",
        )
        after = _nonempty_text(
            row.get("after_effect_id"),
            field="effect_order.after_effect_id",
        )
        if (
            after in before
            or after not in known
            or not set(before) <= known
        ):
            raise ValueError("effect order references invalid effect ids")
        result.append({
            "id": _nonempty_text(
                row.get("id") or f"effect-order-{index:03d}",
                field="effect_order.id",
            ),
            "before_effect_ids": before,
            "after_effect_id": after,
        })
    if len({row["id"] for row in result}) != len(result):
        raise ValueError("duplicate effect order id")
    return result


def _validate_explicit_update_transition_rules(
    rows: Any,
    *,
    effects: list[dict[str, Any]],
    initial_state: Mapping[str, Mapping[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    """Validate author-declared source-state guards for update endpoints."""
    if rows is None:
        return []
    if not isinstance(rows, list) or any(
        not isinstance(row, Mapping) for row in rows
    ):
        raise ValueError("update_transition_rules must be an object list")
    update_effects = {
        (
            str(effect["app"]),
            str(effect["collection"]),
            str(effect["record_id"]),
        ): effect
        for effect in effects
        if effect.get("operation") == "update"
    }
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        app = _nonempty_text(row.get("app"), field="update_transition.app")
        collection = _nonempty_text(
            row.get("collection"),
            field="update_transition.collection",
        )
        before_fields = row.get("before_fields")
        if not isinstance(before_fields, Mapping) or not before_fields:
            raise ValueError(
                "update transition requires non-empty before_fields"
            )
        generic = "record_id" not in row and "patch" not in row
        if generic:
            if set(row) != {
                "app",
                "collection",
                "before_fields",
                "patch_required_fields",
                "patch_exact_fields",
            }:
                raise ValueError(
                    "generic update transition has unexpected fields"
                )
            required_fields = _string_list(
                row.get("patch_required_fields"),
                field="update_transition.patch_required_fields",
            )
            exact_fields = row.get("patch_exact_fields")
            if (
                not required_fields
                or len(set(required_fields)) != len(required_fields)
                or not isinstance(exact_fields, Mapping)
                or not set(exact_fields) <= set(required_fields)
            ):
                raise ValueError("generic update transition patch contract is invalid")
            matching_effects = [
                effect
                for (effect_app, effect_collection, _), effect
                in update_effects.items()
                if effect_app == app and effect_collection == collection
            ]
            if not matching_effects:
                raise ValueError(
                    "generic update transition does not cover an update effect"
                )
            for effect in matching_effects:
                effect_patch = {
                    **copy.deepcopy(dict(effect.get("patch") or {})),
                    **{
                        field: " | ".join(str(token) for token in tokens)
                        for field, tokens in dict(
                            effect.get("contains_fields") or {}
                        ).items()
                    },
                }
                if (
                    set(effect_patch) != set(required_fields)
                    or any(
                        effect_patch.get(field) != expected
                        for field, expected in exact_fields.items()
                    )
                ):
                    raise ValueError(
                        "generic update transition does not match an authored effect"
                    )
                target = next(
                    (
                        record
                        for record in initial_state.get(app, {}).get(collection, [])
                        if str(record.get("id") or "")
                        == str(effect.get("record_id") or "")
                    ),
                    None,
                )
                if target is None or any(
                    target.get(field) != expected
                    for field, expected in before_fields.items()
                ):
                    raise ValueError(
                        "generic update transition before_fields differ from "
                        "an authored target's initial state"
                    )
            record_id = "*"
            patch_contract = {
                "patch_required_fields": required_fields,
                "patch_exact_fields": copy.deepcopy(dict(exact_fields)),
            }
        else:
            if set(row) != {
                "app", "collection", "record_id", "before_fields", "patch"
            }:
                raise ValueError("exact update transition has unexpected fields")
            record_id = _nonempty_text(
                row.get("record_id"),
                field="update_transition.record_id",
            )
            patch = row.get("patch")
            if not isinstance(patch, Mapping) or not patch:
                raise ValueError("exact update transition requires a patch")
            effect = update_effects.get((app, collection, record_id))
            expected_patch = (
                {
                    **copy.deepcopy(dict(effect.get("patch") or {})),
                    **{
                        field: " | ".join(str(token) for token in tokens)
                        for field, tokens in dict(
                            effect.get("contains_fields") or {}
                        ).items()
                    },
                }
                if effect is not None
                else None
            )
            if effect is None or dict(patch) != expected_patch:
                raise ValueError(
                    "update transition must exactly match one authored update effect"
                )
            target = next(
                (
                    record
                    for record in initial_state.get(app, {}).get(collection, [])
                    if str(record.get("id") or "") == record_id
                ),
                None,
            )
            if target is None or any(
                target.get(field) != expected
                for field, expected in before_fields.items()
            ):
                raise ValueError(
                    "update transition before_fields differ from initial target state"
                )
            patch_contract = {"patch": copy.deepcopy(dict(patch))}
        key = (app, collection, record_id, canonical(patch_contract))
        if key in seen:
            raise ValueError("duplicate explicit update transition rule")
        seen.add(key)
        result.append({
            "app": app,
            "collection": collection,
            "record_id": record_id,
            "before_fields": copy.deepcopy(dict(before_fields)),
            **patch_contract,
        })
    return result


def _validate_update_retry_policies(
    rows: Any,
    *,
    collection_specs: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Validate per-collection behavior for a state-equivalent PATCH retry.

    The default remains the historical successful no-op.  Authors may opt a
    collection into a source-state rejection contract when that behavior is a
    genuine part of the product surface.  Keeping this explicit avoids trying
    to infer executable semantics from prose.
    """
    if rows is None:
        return []
    if not isinstance(rows, list) or any(
        not isinstance(row, Mapping) for row in rows
    ):
        raise ValueError("update_retry_policies must be an object list")
    allowed = {"successful_noop", "reject_invalid_transition"}
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if set(row) != {"app", "collection", "state_equivalent_retry"}:
            raise ValueError("update retry policy has unexpected fields")
        app = _nonempty_text(row.get("app"), field="update_retry.app")
        collection = _nonempty_text(
            row.get("collection"), field="update_retry.collection"
        )
        behavior = _nonempty_text(
            row.get("state_equivalent_retry"),
            field="update_retry.state_equivalent_retry",
        )
        spec = collection_specs.get((app, collection))
        if spec is None or "update" not in spec.get("operations", []):
            raise ValueError("update retry policy must reference an update collection")
        if behavior not in allowed:
            raise ValueError("unsupported state-equivalent update retry policy")
        key = (app, collection)
        if key in seen:
            raise ValueError("duplicate update retry policy")
        seen.add(key)
        result.append({
            "app": app,
            "collection": collection,
            "state_equivalent_retry": behavior,
        })
    return result


def _validate_required_readbacks(
    rows: Any,
    *,
    effects: list[dict[str, Any]],
    collection_specs: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if rows is None:
        return []
    if not isinstance(rows, list) or any(
        not isinstance(row, Mapping) for row in rows
    ):
        raise ValueError("required_readbacks must be an object list")
    effect_ids = {row["id"] for row in effects}
    result: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        app = _nonempty_text(row.get("app"), field="readback.app")
        collection = _nonempty_text(
            row.get("collection"),
            field="readback.collection",
        )
        spec = collection_specs.get((app, collection))
        record_id = row.get("record_id")
        query = row.get("query")
        after_effect_id = _nonempty_text(
            row.get("after_effect_id"),
            field="readback.after_effect_id",
        )
        exact_fields = row.get("exact_fields", {})
        if (
            spec is None
            or not {"search", "read"} & set(spec["operations"])
            or (record_id is None) == (query is None)
            or after_effect_id not in effect_ids
            or not isinstance(exact_fields, dict)
        ):
            raise ValueError("required readback has an invalid boundary")
        value: dict[str, Any] = {
            "id": _nonempty_text(
                row.get("id") or f"required-readback-{index:03d}",
                field="readback.id",
            ),
            "app": app,
            "collection": collection,
            "after_effect_id": after_effect_id,
            "exact_fields": copy.deepcopy(exact_fields),
        }
        if record_id is not None:
            value["record_id"] = _nonempty_text(
                record_id,
                field="readback.record_id",
            )
        else:
            if not isinstance(query, dict) or not query:
                raise ValueError(
                    "required readback query must be a non-empty object"
                )
            # A future create is often addressed by its public business ID.
            # Normalize an exact one-field identity query to the created
            # record ID so the scorer accepts either native item GET or a
            # complete search that actually returns that same record.  This
            # also prevents a complete zero-row search from masquerading as a
            # successful post-write readback.
            matching_created_effects = [
                effect
                for effect in effects
                if effect.get("operation") == "create"
                and effect.get("app") == app
                and effect.get("collection") == collection
                and effect.get("record_id") is not None
                and len(query) == 1
                and next(iter(query.values()))
                == effect.get("record_id")
            ]
            query_field = next(iter(query)) if len(query) == 1 else None
            if (
                len(matching_created_effects) == 1
                and isinstance(query_field, str)
                and query_field.endswith("_id")
            ):
                created_id = str(
                    matching_created_effects[0]["record_id"]
                )
                value["record_id"] = created_id
                if value["exact_fields"].get(query_field) == created_id:
                    value["exact_fields"].pop(query_field)
                value["equivalent_search_query"] = copy.deepcopy(query)
            else:
                value["query"] = copy.deepcopy(query)
        result.append(value)
    if len({row["id"] for row in result}) != len(result):
        raise ValueError("duplicate required readback id")
    return result


def _validate_forbidden(
    rows: Any,
    *,
    initial_state: Mapping[str, Mapping[str, list[dict[str, Any]]]],
    allow_empty: bool = False,
) -> list[dict[str, Any]]:
    if allow_empty and (rows is None or rows == ()):
        return []
    if allow_empty and isinstance(rows, list) and not rows:
        return []
    if not isinstance(rows, list) or not rows:
        raise ValueError("forbidden_unchanged must be a non-empty list")
    result = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("forbidden rows must be objects")
        app = _nonempty_text(row.get("app"), field="forbidden.app")
        collection = _nonempty_text(
            row.get("collection"),
            field="forbidden.collection",
        )
        record_id = _nonempty_text(
            row.get("record_id"),
            field="forbidden.record_id",
        )
        fields = row.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise ValueError("forbidden fields must be a non-empty object")
        records = initial_state.get(app, {}).get(collection, [])
        target = next(
            (record for record in records if str(record.get("id")) == record_id),
            None,
        )
        if target is None or any(
            target.get(field) != expected
            for field, expected in fields.items()
        ):
            raise ValueError(
                "forbidden unchanged fields differ from initial state"
            )
        # ``id`` is the private row locator used by the runtime.  It is
        # checked by collection closure/state contracts through record_id,
        # but it is never a business field and must not enter field-level
        # reviewer or student projections.
        business_fields = {
            str(field): copy.deepcopy(expected)
            for field, expected in fields.items()
            if str(field) != "id"
        }
        if not business_fields:
            raise ValueError(
                "forbidden fields must include at least one business field"
            )
        result.append({
            "app": app,
            "collection": collection,
            "record_id": record_id,
            "fields": business_fields,
        })
    return result


def _validate_error_code_policy(
    value: Any,
    *,
    required_feature_conditions: set[str],
) -> dict[str, str]:
    if value is None:
        return {}
    required = CORE_PUBLIC_ERROR_CONDITIONS | required_feature_conditions
    if (
        not isinstance(value, Mapping)
        or not required <= set(value)
        or not set(value) <= PUBLIC_ERROR_CONDITIONS
    ):
        raise ValueError(
            "error_code_policy must map every core rejection condition and "
            "each feature-specific condition exposed by this task"
        )
    result: dict[str, str] = {}
    for condition, code in value.items():
        if (
            not isinstance(code, str)
            or not re.fullmatch(r"[A-Z][A-Z0-9_]*", code)
        ):
            raise ValueError(
                f"error_code_policy.{condition} must be an uppercase code"
            )
        result[str(condition)] = code
    return result


def _expand_unchanged_baseline_policy(
    value: Any,
    *,
    initial_state: Mapping[str, Mapping[str, list[dict[str, Any]]]],
    effects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if value is None:
        return []
    if (
        not isinstance(value, Mapping)
        or set(value) != {"scope", "allowed_field_changes"}
        or value.get("scope") != "all_initial_records"
        or not isinstance(value.get("allowed_field_changes"), list)
    ):
        raise ValueError("unchanged_baseline_policy is malformed")
    allowed: dict[tuple[str, str, str], set[str]] = {}
    update_fields: dict[tuple[str, str, str], set[str]] = {}
    for effect in effects:
        if effect.get("operation") != "update":
            continue
        key = (
            str(effect["app"]),
            str(effect["collection"]),
            str(effect["record_id"]),
        )
        update_fields.setdefault(key, set()).update({
            *map(str, effect.get("patch", {})),
            *map(str, effect.get("contains_fields", {})),
        })
    for row in value["allowed_field_changes"]:
        if (
            not isinstance(row, Mapping)
            or set(row) != {
                "app",
                "collection",
                "record_id",
                "fields",
            }
            or not isinstance(row.get("fields"), list)
            or not row["fields"]
            or any(
                not isinstance(field, str)
                or not field
                or field == "id"
                for field in row["fields"]
            )
        ):
            raise ValueError(
                "unchanged_baseline_policy allowed change is malformed"
            )
        key = (
            _nonempty_text(
                row.get("app"),
                field="unchanged_baseline_policy.app",
            ),
            _nonempty_text(
                row.get("collection"),
                field="unchanged_baseline_policy.collection",
            ),
            _nonempty_text(
                row.get("record_id"),
                field="unchanged_baseline_policy.record_id",
            ),
        )
        fields = set(row["fields"])
        if (
            key in allowed
            or key not in update_fields
            or fields != update_fields[key]
        ):
            raise ValueError(
                "unchanged_baseline_policy must exactly match one "
                "authored update target"
            )
        records = initial_state.get(key[0], {}).get(key[1], [])
        target = next(
            (
                record
                for record in records
                if str(record.get("id") or "") == key[2]
            ),
            None,
        )
        if target is None or not fields <= set(target):
            raise ValueError(
                "unchanged_baseline_policy target or field is absent"
            )
        allowed[key] = fields
    if set(allowed) != set(update_fields):
        raise ValueError(
            "unchanged_baseline_policy must enumerate every update target"
        )
    expanded = []
    for app, collections in initial_state.items():
        for collection, records in collections.items():
            for record in records:
                record_id = str(record.get("id") or "")
                fields = {
                    str(field): copy.deepcopy(field_value)
                    for field, field_value in record.items()
                    if str(field) != "id"
                    and str(field)
                    not in allowed.get(
                        (str(app), str(collection), record_id),
                        set(),
                    )
                }
                if fields:
                    expanded.append({
                        "app": str(app),
                        "collection": str(collection),
                        "record_id": record_id,
                        "fields": fields,
                    })
    if not expanded:
        raise ValueError("unchanged_baseline_policy expanded to no rows")
    return expanded


def _validate_emitted_artifacts(
    rows: Any,
    *,
    collection_specs: Mapping[tuple[str, str], Mapping[str, Any]],
    initial_state: Mapping[str, Mapping[str, list[dict[str, Any]]]],
    effects: list[dict[str, Any]],
    fallback_only: bool = False,
) -> list[dict[str, Any]]:
    """Validate system-written artifacts against one explicit producer effect.

    These records are not additional student actions.  They are atomic
    consequences of a documented update/create/send and may live in a
    student-readable but write-inaccessible collection.
    """

    if rows is None:
        return []
    if not isinstance(rows, list) or any(
        not isinstance(row, Mapping) for row in rows
    ):
        raise ValueError("mutation_emitted_artifacts must be an object list")

    result: list[dict[str, Any]] = []
    artifact_identities: set[tuple[str, str, str]] = set()
    for index, row in enumerate(rows, 1):
        producer = row.get("producer")
        artifact = row.get("artifact")
        if not isinstance(producer, Mapping) or not isinstance(
            artifact, Mapping
        ):
            raise ValueError("emitted artifact requires producer and artifact")

        operation = _nonempty_text(
            producer.get("operation"),
            field="emitted.producer.operation",
        )
        producer_app = _nonempty_text(
            producer.get("app"),
            field="emitted.producer.app",
        )
        producer_collection = _nonempty_text(
            producer.get("collection"),
            field="emitted.producer.collection",
        )
        producer_record_id = _nonempty_text(
            producer.get("record_id"),
            field="emitted.producer.record_id",
        )
        match_fields = producer.get("match_fields")
        before_fields = producer.get("before_fields", {})
        if (
            operation not in {"update", "create", "send"}
            or not isinstance(match_fields, dict)
            or not match_fields
            or not isinstance(before_fields, dict)
        ):
            raise ValueError(
                "emitted artifact producer requires a mutation and exact "
                "match_fields"
            )
        if operation != "update" and before_fields:
            raise ValueError(
                "only update producers may declare before_fields"
            )
        if operation == "update" and before_fields:
            producer_rows = initial_state.get(
                producer_app,
                {},
            ).get(producer_collection, [])
            initial_target = next(
                (
                    record
                    for record in producer_rows
                    if str(record.get("id") or "")
                    == producer_record_id
                ),
                None,
            )
            if initial_target is None or any(
                initial_target.get(field) != value
                for field, value in before_fields.items()
            ):
                raise ValueError(
                    "update producer before_fields do not match the initial "
                    "target"
                )

        producer_matches: list[tuple[int, dict[str, Any]]] = []
        for effect_index, effect in enumerate(effects):
            if (
                effect["operation"] != operation
                or effect["app"] != producer_app
                or effect["collection"] != producer_collection
            ):
                continue
            effect_ids = (
                {str(effect.get("record_id") or "")}
                if effect.get("record_id") is not None
                else {
                    str(value)
                    for value in effect.get("record_id_any_of", [])
                }
            )
            if producer_record_id not in effect_ids:
                continue
            if operation == "update":
                expected_match = effect.get("patch", {})
            elif operation == "create":
                expected_match = effect.get("required_patch", {})
            else:
                expected_match = {
                    "channel": effect.get("channel"),
                    "message_contains_all": effect.get("contains_all"),
                }
            if match_fields == expected_match:
                producer_matches.append((effect_index, effect))
        if fallback_only:
            if producer_matches:
                raise ValueError(
                    "fallback emitted artifact overlaps an expected effect"
                )
            producer_spec = collection_specs.get(
                (producer_app, producer_collection)
            )
            matching_id_rules = [
                rule
                for rule in (
                    producer_spec.get("server_generated_id_rules", [])
                    if producer_spec is not None
                    else []
                )
                if str(rule.get("id") or "") == producer_record_id
                and rule.get("match_fields") == match_fields
            ]
            if operation != "create" or len(matching_id_rules) != 1:
                raise ValueError(
                    "fallback emitted artifact must bind to exactly one "
                    "agent-authored create ID rule"
                )
            producer_effect_index: int | None = None
        else:
            if len(producer_matches) != 1:
                raise ValueError(
                    "emitted artifact must bind to exactly one complete "
                    "expected producer effect"
                )
            producer_effect_index = producer_matches[0][0]

        artifact_app = _nonempty_text(
            artifact.get("app"),
            field="emitted.artifact.app",
        )
        artifact_collection = _nonempty_text(
            artifact.get("collection"),
            field="emitted.artifact.collection",
        )
        artifact_record_id = _nonempty_text(
            artifact.get("record_id"),
            field="emitted.artifact.record_id",
        )
        artifact_fields = artifact.get("fields")
        runtime_fields = artifact.get("runtime_fields", {})
        artifact_spec = collection_specs.get(
            (artifact_app, artifact_collection)
        )
        if (
            artifact_spec is None
            or not {"search", "read"} & set(artifact_spec["operations"])
            or not isinstance(artifact_fields, dict)
            or not artifact_fields
            or not isinstance(runtime_fields, Mapping)
            or any(
                not isinstance(field, str)
                or not field
                or mode != "commit_utc"
                for field, mode in runtime_fields.items()
            )
            or set(runtime_fields) & set(artifact_fields)
        ):
            raise ValueError(
                "emitted artifact must target an ordinary readable collection "
                "with exact fields"
            )
        assertion_fields = copy.deepcopy(artifact_fields)
        normalized_fields = copy.deepcopy(artifact_fields)
        if (
            "id" in normalized_fields
            and str(normalized_fields["id"]) != artifact_record_id
        ):
            raise ValueError("emitted artifact id conflicts with fields.id")
        native_identity_field = artifact_spec.get("identity_field")
        if native_identity_field is not None:
            if (
                native_identity_field in normalized_fields
                and str(normalized_fields[native_identity_field])
                != artifact_record_id
            ):
                raise ValueError(
                    "emitted artifact native identity conflicts with "
                    "artifact.record_id"
                )
            normalized_fields[native_identity_field] = artifact_record_id
            assertion_fields[native_identity_field] = artifact_record_id
        normalized_fields["id"] = artifact_record_id
        identity = (
            artifact_app,
            artifact_collection,
            artifact_record_id,
        )
        if identity in artifact_identities:
            raise ValueError("duplicate emitted artifact identity")
        artifact_identities.add(identity)
        if any(
            str(existing.get("id") or "") == artifact_record_id
            for existing in initial_state.get(
                artifact_app, {}
            ).get(artifact_collection, [])
        ):
            raise ValueError("emitted artifact collides with initial state")

        result.append({
            "id": _nonempty_text(
                row.get("id") or f"emitted-{index:03d}",
                field="emitted.id",
            ),
            "producer_effect_index": producer_effect_index,
            "fallback_only": fallback_only,
            "producer": {
                "operation": operation,
                "app": producer_app,
                "collection": producer_collection,
                "record_id": producer_record_id,
                "match_fields": copy.deepcopy(match_fields),
                "before_fields": copy.deepcopy(before_fields),
            },
            "artifact": {
                "app": artifact_app,
                "collection": artifact_collection,
                "record_id": artifact_record_id,
                "fields": normalized_fields,
                "assertion_fields": assertion_fields,
                "runtime_fields": copy.deepcopy(dict(runtime_fields)),
            },
        })
    if len({row["id"] for row in result}) != len(result):
        raise ValueError("duplicate emitted artifact contract id")
    return result


def _typed_relationship_assertions(
    *,
    initial_state: Mapping[str, Mapping[str, list[dict[str, Any]]]],
    runtime_config: Mapping[str, Any],
    effects: list[dict[str, Any]],
    emitted_artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compile authored foreign-key metadata into terminal edge checks."""
    terminal_state = copy.deepcopy(initial_state)
    identity_fields = runtime_config.get("identity_fields", {})
    for effect in effects:
        app = str(effect["app"])
        collection = str(effect["collection"])
        rows = terminal_state[app][collection]
        operation = str(effect["operation"])
        if operation == "update":
            target = next(
                (
                    row
                    for row in rows
                    if str(row.get("id") or "")
                    == str(effect.get("record_id") or "")
                ),
                None,
            )
            if target is not None:
                target.update(copy.deepcopy(effect.get("patch", {})))
        elif operation == "create" and effect.get("record_id") is not None:
            record_id = str(effect["record_id"])
            row = {
                "id": record_id,
                **copy.deepcopy(effect.get("required_patch", {})),
            }
            identity_field = (
                identity_fields.get(app, {}).get(collection)
                if isinstance(identity_fields, Mapping)
                else None
            )
            if isinstance(identity_field, str) and identity_field:
                row[identity_field] = record_id
            rows.append(row)
    for emitted in emitted_artifacts:
        artifact = emitted["artifact"]
        terminal_state[artifact["app"]][artifact["collection"]].append(
            copy.deepcopy(artifact["fields"])
        )

    foreign_keys = runtime_config.get("foreign_keys", {})
    assertions: list[dict[str, Any]] = []
    for app, collections in sorted(terminal_state.items()):
        for collection, rows in sorted(collections.items()):
            relationships = (
                foreign_keys.get(app, {}).get(collection, [])
                if isinstance(foreign_keys, Mapping)
                else []
            )
            for row in rows:
                source_record_id = str(row.get("id") or "")
                for relationship in relationships:
                    field = str(relationship["field"])
                    if field not in row or row.get(field) in {None, ""}:
                        continue
                    expected = copy.deepcopy(row[field])
                    target_rows = terminal_state.get(
                        relationship["app"], {}
                    ).get(relationship["collection"], [])
                    matches = [
                        target
                        for target in target_rows
                        if target.get(relationship["target_field"])
                        == expected
                    ]
                    if len(matches) != 1:
                        raise ValueError(
                            "typed relationship does not resolve exactly "
                            f"once: {app}/{collection}/{source_record_id}."
                            f"{field} -> {relationship['app']}/"
                            f"{relationship['collection']}."
                            f"{relationship['target_field']}"
                        )
                    assertions.append({
                        "id": (
                            "typed-edge-"
                            f"{len(assertions) + 1:04d}-"
                            f"{_slug(app)}-{_slug(collection)}-"
                            f"{_slug(source_record_id)}-{_slug(field)}"
                        ),
                        "type": "typed_relationship_edge",
                        "app": app,
                        "collection": collection,
                        "record_id": source_record_id,
                        "field": field,
                        "expected_target_value": expected,
                        "target_app": relationship["app"],
                        "target_collection": relationship["collection"],
                        "target_field": relationship["target_field"],
                        **(
                            {"role": relationship["role"]}
                            if relationship.get("role")
                            else {}
                        ),
                        "exact_target_count": 1,
                        "depends_on": [],
                    })
    return assertions


def compile_runtime_source(
    *,
    candidate_markdown: str,
    candidate_relative_path: str,
    source: Mapping[str, Any],
    domain_label: str,
    rubric_sha256: str,
) -> dict[str, Any]:
    candidate_sha = markdown_sha256(candidate_markdown)
    if source.get("schema_version") != RUNTIME_SOURCE_SCHEMA:
        raise ValueError("unexpected runtime source schema")
    if source.get("candidate_markdown_sha256") != candidate_sha:
        raise ValueError("runtime source is not bound to the candidate Markdown")
    authored_task_instruction = source.get("task_instruction")
    if authored_task_instruction is None:
        authored_task_instruction = source.get("student_instruction")
    if authored_task_instruction is None:
        # Backward-compatible read path for historical packages.  New
        # complete-task authors bind the student instruction explicitly so a
        # harmless change in Markdown heading wording cannot reject an
        # otherwise complete task.
        student_request = extract_task_request(candidate_markdown)
    else:
        student_request = _nonempty_text(
            authored_task_instruction,
            field="task_instruction",
        )
        if len(student_request) < 120:
            raise ValueError("task_instruction is too short")
        if student_request not in candidate_markdown:
            raise ValueError(
                "task_instruction must appear verbatim in candidate Markdown"
            )
    (
        allowed_apps,
        app_capabilities,
        initial_state,
        catalog,
        runtime_config,
        collection_specs,
    ) = _source_rows(source)
    raw_list_semantics = source.get("list_semantics")
    if raw_list_semantics is not None:
        if (
            not isinstance(raw_list_semantics, Mapping)
            or set(raw_list_semantics) != {
                "pagination_enabled",
                "default_limit",
                "limit_min",
                "limit_max",
                "cursor_kind",
                "cursor_semantics",
                "stable_sort",
                "different_filters",
                "in_csv_members",
                "reject_empty_csv_members",
                "reject_unknown_query_parameters",
                "live_current_state",
            }
            or raw_list_semantics.get("pagination_enabled") is not True
            or not isinstance(raw_list_semantics.get("default_limit"), int)
            or not isinstance(raw_list_semantics.get("limit_min"), int)
            or not isinstance(raw_list_semantics.get("limit_max"), int)
            or not (
                1
                <= int(raw_list_semantics["limit_min"])
                <= int(raw_list_semantics["default_limit"])
                <= int(raw_list_semantics["limit_max"])
                <= 100
            )
            or raw_list_semantics.get("cursor_kind") != "opaque"
            or raw_list_semantics.get("cursor_semantics")
            != "live_keyset_route_filter_bound"
            or raw_list_semantics.get("stable_sort")
            != "native_identity_ascending"
            or raw_list_semantics.get("different_filters") != "and"
            or raw_list_semantics.get("in_csv_members") != "or"
            or raw_list_semantics.get("reject_empty_csv_members") is not True
            or raw_list_semantics.get(
                "reject_unknown_query_parameters"
            ) is not True
            or raw_list_semantics.get("live_current_state") is not True
        ):
            raise ValueError("runtime source list_semantics is malformed")
        list_semantics = copy.deepcopy(dict(raw_list_semantics))
        runtime_config["list_semantics"] = list_semantics
        for endpoint in catalog:
            if endpoint.get("operation") != "search":
                continue
            endpoint["params_fields"] = list(dict.fromkeys([
                *endpoint.get("params_fields", []),
                "limit",
                "cursor",
            ]))
            endpoint["description"] += (
                f" Results use current live state, default limit "
                f"{list_semantics['default_limit']}, accepted limit "
                f"{list_semantics['limit_min']}.."
                f"{list_semantics['limit_max']}, ascending native-identity "
                "order, and an opaque live keyset cursor bound to this route "
                "and its non-pagination filters; "
                "next_cursor is returned only when another page exists. Each "
                "continuation re-reads current state and returns native "
                "identities strictly after the cursor identity; inserts at "
                "or before that identity are not replayed, while later "
                "inserts may appear."
            )
            source_spec = collection_specs[
                (str(endpoint["app"]), str(endpoint["collection"]))
            ]
            if any(
                rule.get("operator") == "in_csv"
                for rule in source_spec["search_rules"].values()
            ):
                endpoint["description"] += (
                    " Comma-separated membership values are OR within their "
                    "field; members are trimmed and empty members are "
                    "rejected. Membership comparison is case-sensitive unless "
                    "that parameter is explicitly documented as case-folded."
                )
    raw_release_clock = source.get("release_clock_utc")
    if raw_release_clock is not None:
        if not isinstance(raw_release_clock, str) or not raw_release_clock.endswith(
            "Z"
        ):
            raise ValueError(
                "release_clock_utc must be an ISO-8601 UTC timestamp ending Z"
            )
        try:
            release_clock = datetime.fromisoformat(
                raw_release_clock.removesuffix("Z") + "+00:00"
            )
        except ValueError as exc:
            raise ValueError(
                "release_clock_utc must be an ISO-8601 UTC timestamp"
            ) from exc
        if release_clock.utcoffset() != timezone.utc.utcoffset(
            release_clock
        ):
            raise ValueError("release_clock_utc must be UTC")
        runtime_config["commit_clock_utc"] = raw_release_clock
    required_feature_error_conditions: set[str] = set()
    if any(
        "cursor" in endpoint.get("params_fields", [])
        for endpoint in catalog
        if endpoint.get("operation") == "search"
    ):
        required_feature_error_conditions.add("invalid_cursor")
    if any(
        rule.get("operator") == "in_csv"
        for spec in collection_specs.values()
        for rule in spec["search_rules"].values()
    ):
        required_feature_error_conditions.add("invalid_csv")
    if any(
        expansions
        for collections in dict(
            runtime_config.get("read_expansions") or {}
        ).values()
        for expansions in dict(collections or {}).values()
    ):
        required_feature_error_conditions.add("unsupported_expansion")
    error_code_policy = _validate_error_code_policy(
        source.get("error_code_policy"),
        required_feature_conditions=required_feature_error_conditions,
    )
    if error_code_policy:
        runtime_config["public_error_code_policy"] = copy.deepcopy(
            error_code_policy
        )
        rendered_error_codes = "; ".join(
            f"{condition}={code}"
            for condition, code in sorted(error_code_policy.items())
        )
        for endpoint in catalog:
            endpoint["description"] += (
                " Exact visible rejection-code mapping: "
                f"{rendered_error_codes}. "
                + (
                    "Rejected responses contain only the documented code "
                    "and message fields."
                    if isinstance(
                        endpoint.get("error_response_contract"), dict
                    )
                    else "Rejected responses use exactly ok=false and put "
                    "the stable visible code in error."
                )
            )
    evidence = _validate_evidence(
        source.get("required_evidence"),
        collection_specs=collection_specs,
    )
    derivation_coverage = _validate_evidence(
        source.get("derivation_coverage", []),
        collection_specs=collection_specs,
    )
    observation_rows = [*evidence, *derivation_coverage]
    if (
        len(observation_rows) < 2
        or len({row["app"] for row in observation_rows}) < 2
    ):
        raise ValueError(
            "runtime source evidence/derivation coverage must contain at "
            "least two observations spanning two applications"
        )
    effects = _validate_effects(
        source.get("expected_effects"),
        collection_specs=collection_specs,
    )
    explicit_update_transition_rules = (
        _validate_explicit_update_transition_rules(
            source.get("update_transition_rules"),
            effects=effects,
            initial_state=initial_state,
        )
    )
    update_retry_policies = _validate_update_retry_policies(
        source.get("update_retry_policies"),
        collection_specs=collection_specs,
    )
    runtime_config["update_retry_policies"] = copy.deepcopy(
        update_retry_policies
    )
    reject_retry_keys = {
        (row["app"], row["collection"])
        for row in update_retry_policies
        if row["state_equivalent_retry"] == "reject_invalid_transition"
    }
    for endpoint in catalog:
        if (
            endpoint.get("operation") == "update"
            and (endpoint.get("app"), endpoint.get("collection"))
            in reject_retry_keys
        ):
            endpoint["description"] = endpoint["description"].replace(
                "A state-equivalent retry is a successful no-op with "
                "mutation_applied=false and emits no additional side "
                "effect. The response never contains a changed field.",
                "A state-equivalent retry is rejected as invalid_transition "
                "with mutation_applied=false and emits no additional side "
                "effect. Recover an uncertain response by reading the "
                "current record. The response never contains a changed field.",
            )
    evidence_dependencies_by_effect = (
        _validate_evidence_effect_dependencies(
            source.get("evidence_effect_dependencies", []),
            evidence=evidence,
            effects=effects,
        )
    )
    effect_order_constraints = _validate_effect_order_constraints(
        source.get("effect_order_constraints"),
        effects=effects,
    )
    runtime_config["effect_order_constraints"] = copy.deepcopy(
        effect_order_constraints
    )
    required_readbacks = _validate_required_readbacks(
        source.get("required_readbacks"),
        effects=effects,
        collection_specs=collection_specs,
    )
    emitted_artifacts = _validate_emitted_artifacts(
        source.get("mutation_emitted_artifacts"),
        collection_specs=collection_specs,
        initial_state=initial_state,
        effects=effects,
    )
    fallback_emitted_artifacts = _validate_emitted_artifacts(
        source.get("fallback_mutation_emitted_artifacts", []),
        collection_specs=collection_specs,
        initial_state=initial_state,
        effects=effects,
        fallback_only=True,
    )
    emitted_identities = [
        (
            row["artifact"]["app"],
            row["artifact"]["collection"],
            row["artifact"]["record_id"],
        )
        for row in [
            *emitted_artifacts,
            *fallback_emitted_artifacts,
        ]
    ]
    if len(emitted_identities) != len(set(emitted_identities)):
        raise ValueError(
            "expected and fallback emitted artifacts share an identity"
        )
    baseline_policy = source.get("unchanged_baseline_policy")
    explicit_forbidden = _validate_forbidden(
        source.get("forbidden_unchanged"),
        initial_state=initial_state,
        allow_empty=baseline_policy is not None,
    )
    policy_forbidden = _expand_unchanged_baseline_policy(
        baseline_policy,
        initial_state=initial_state,
        effects=effects,
    )
    if policy_forbidden:
        policy_by_identity = {
            (row["app"], row["collection"], row["record_id"]): row["fields"]
            for row in policy_forbidden
        }
        for row in explicit_forbidden:
            identity = (
                row["app"],
                row["collection"],
                row["record_id"],
            )
            policy_fields = policy_by_identity.get(identity)
            if policy_fields is None or any(
                field not in policy_fields
                or policy_fields[field] != expected
                for field, expected in row["fields"].items()
            ):
                raise ValueError(
                    "forbidden_unchanged contradicts "
                    "unchanged_baseline_policy"
                )
        forbidden = policy_forbidden
    else:
        forbidden = explicit_forbidden
    runtime_config["mutation_emitted_artifacts"] = copy.deepcopy([
        *emitted_artifacts,
        *fallback_emitted_artifacts,
    ])
    runtime_config["emitted_artifact_id_rules"] = [
        {
            "mapping_id": row["id"],
            "fallback_only": row.get("fallback_only") is True,
            "producer": copy.deepcopy(row["producer"]),
            "artifact": {
                "app": row["artifact"]["app"],
                "collection": row["artifact"]["collection"],
                "record_id": row["artifact"]["record_id"],
                "exact_fields": copy.deepcopy(
                    row["artifact"]["assertion_fields"]
                ),
                "runtime_fields": copy.deepcopy(
                    row["artifact"]["runtime_fields"]
                ),
            },
        }
        for row in [
            *emitted_artifacts,
            *fallback_emitted_artifacts,
        ]
    ]
    runtime_config["fallback_mutation_emitted_artifacts"] = copy.deepcopy(
        fallback_emitted_artifacts
    )
    emitted_update_transition_rules = [
        {
            "app": row["producer"]["app"],
            "collection": row["producer"]["collection"],
            "record_id": row["producer"]["record_id"],
            "before_fields": copy.deepcopy(
                row["producer"].get("before_fields", {})
            ),
            "patch": copy.deepcopy(row["producer"]["match_fields"]),
        }
        for row in [*emitted_artifacts, *fallback_emitted_artifacts]
        if row["producer"]["operation"] == "update"
        and row["producer"].get("before_fields")
    ]
    transition_keys: set[tuple[str, str, str, str]] = set()
    combined_transition_rules: list[dict[str, Any]] = []
    for row in [
        *explicit_update_transition_rules,
        *emitted_update_transition_rules,
    ]:
        key = (
            str(row["app"]),
            str(row["collection"]),
            str(row["record_id"]),
            canonical({
                key: row.get(key)
                for key in (
                    "patch", "patch_required_fields", "patch_exact_fields"
                )
                if key in row
            }),
        )
        if key in transition_keys:
            existing = next(
                item
                for item in combined_transition_rules
                if (
                    str(item["app"]),
                    str(item["collection"]),
                    str(item["record_id"]),
                    canonical({
                        key: item.get(key)
                        for key in (
                            "patch", "patch_required_fields", "patch_exact_fields"
                        )
                        if key in item
                    }),
                )
                == key
            )
            if existing["before_fields"] != row["before_fields"]:
                raise ValueError("conflicting update transition rules")
            continue
        transition_keys.add(key)
        combined_transition_rules.append(copy.deepcopy(row))
    runtime_config["update_transition_rules"] = combined_transition_rules
    transition_doc_keys = {
        (
            row["app"],
            row["collection"],
            tuple(sorted(row["before_fields"])),
            tuple(sorted(
                row.get("patch_required_fields") or row.get("patch", {})
            )),
        )
        for row in explicit_update_transition_rules
    } | {
        (
            row["producer"]["app"],
            row["producer"]["collection"],
            tuple(sorted(row["producer"]["before_fields"])),
            tuple(sorted(row["producer"]["match_fields"])),
        )
        for row in [*emitted_artifacts, *fallback_emitted_artifacts]
        if row["producer"]["operation"] == "update"
        and row["producer"].get("before_fields")
    }
    for app, collection, before_fields, patch_fields in sorted(
        transition_doc_keys
    ):
        for endpoint in catalog:
            if (
                endpoint.get("operation") == "update"
                and endpoint.get("app") == app
                and endpoint.get("collection") == collection
            ):
                endpoint["description"] += (
                    " State-changing requests enforce documented source-state "
                    "preconditions on fields "
                    f"{', '.join(before_fields)} and transition body fields "
                    f"{', '.join(patch_fields)}. The same documented validation "
                    "applies to every addressable record in this collection."
                )
    producer_doc_keys = {
        (
            emitted["producer"]["operation"],
            emitted["producer"]["app"],
            emitted["producer"]["collection"],
        )
        for emitted in [*emitted_artifacts, *fallback_emitted_artifacts]
    }
    for operation, app, collection in sorted(producer_doc_keys):
        response_flag = {
            "create": "created=true",
            "update": "mutation_applied=true",
            "send": "mutation_applied=true",
        }[operation]
        for endpoint in catalog:
            if (
                endpoint.get("operation") == operation
                and endpoint.get("app") == app
                and endpoint.get("collection") == collection
            ):
                endpoint["description"] += (
                    " On the first successful state-changing request, all "
                    "validation completes before any server ID is allocated; "
                    f"the response reports {response_flag} and returns the "
                    "primary record plus singular event_id when exactly one "
                    "event artifact is emitted. The primary mutation "
                    "and its emitted artifacts commit atomically. "
                    + (
                        "An exact retry is rejected as invalid_transition "
                        "with mutation_applied=false and emits no second "
                        "artifact."
                        if operation == "update"
                        and (app, collection) in reject_retry_keys
                        else "An exact retry is a successful no-op and emits "
                        "no second artifact."
                    )
                )
    artifact_doc_fields: dict[tuple[str, str], set[str]] = {}
    for emitted in [*emitted_artifacts, *fallback_emitted_artifacts]:
        artifact = emitted["artifact"]
        artifact_doc_fields.setdefault(
            (artifact["app"], artifact["collection"]),
            set(),
        ).update({
            *(
                field
                for field in artifact["fields"]
                if field != "id"
            ),
            *artifact.get("runtime_fields", {}),
        })
    configured_foreign_keys = runtime_config.get("foreign_keys", {})
    for (app, collection), spec in sorted(collection_specs.items()):
        identity_field = (
            runtime_config.get("identity_fields", {})
            .get(app, {})
            .get(collection)
        )
        visible_fields = {
            *spec.get("record_fields", []),
            *spec.get("create_fields", []),
            *spec.get("update_fields", []),
            *artifact_doc_fields.get((app, collection), set()),
        }
        visible_fields.discard("id")
        if identity_field:
            visible_fields.add(identity_field)
        foreign_key_rows = (
            configured_foreign_keys.get(app, {}).get(collection, [])
            if isinstance(configured_foreign_keys, dict)
            else []
        )
        foreign_key_text = "; ".join(
            (
                (
                    f"{row['role']}: "
                    if row.get("role")
                    else ""
                )
                + _foreign_key_description(row)
            )
            for row in foreign_key_rows
        ) or "none"
        for endpoint in catalog:
            if (
                endpoint.get("operation") in {"search", "read"}
                and endpoint.get("app") == app
                and endpoint.get("collection") == collection
            ):
                endpoint["description"] += (
                    " Returned records expose exactly these business fields"
                    + (
                        f", with native identity {identity_field}: "
                        if identity_field
                        else ": "
                    )
                    + f"{', '.join(sorted(visible_fields))}. Foreign keys: "
                    f"{foreign_key_text}."
                )
                if (app, collection) in artifact_doc_fields:
                    endpoint["description"] += (
                        " `occurred_at` is the mutation commit time in UTC."
                    )
                if endpoint.get("operation") == "read":
                    expansion_descriptions = []
                    for expansion in spec.get("read_expansions", []):
                        target_spec = collection_specs.get((
                            str(expansion.get("app") or ""),
                            str(expansion.get("collection") or ""),
                        ))
                        if target_spec is None:
                            continue
                        target_app = str(expansion["app"])
                        target_collection = str(
                            expansion["collection"]
                        )
                        target_fields = {
                            *target_spec.get("record_fields", []),
                            *target_spec.get("create_fields", []),
                            *target_spec.get("update_fields", []),
                            *artifact_doc_fields.get(
                                (target_app, target_collection),
                                set(),
                            ),
                        }
                        target_fields.discard("id")
                        target_identity = (
                            runtime_config.get("identity_fields", {})
                            .get(target_app, {})
                            .get(target_collection)
                        )
                        if target_identity:
                            target_fields.add(target_identity)
                        expansion_descriptions.append(
                            f"`{expansion['name']}` is an array of live "
                            f"immediate, non-recursive "
                            f"{target_app}/{target_collection} children "
                            f"whose `{expansion['foreign_key']}` equals the "
                            "parent native identity; each child exposes "
                            + (
                                f"native identity `{target_identity}` and "
                                if target_identity
                                else ""
                            )
                            + "exactly these fields: "
                            + ", ".join(sorted(target_fields))
                        )
                    if expansion_descriptions:
                        endpoint["description"] += (
                            " Expansion response schemas: "
                            + "; ".join(expansion_descriptions)
                            + "."
                        )

    evidence_assertions = [
        {
            "id": row["id"],
            "type": "evidence_read",
            "app": row["app"],
            "collection": row["collection"],
            **(
                {"record_id": row["record_id"]}
                if "record_id" in row
                else {"query": row["query"]}
            ),
            "oracle_operation": row["oracle_operation"],
            **(
                {"oracle_query": row["oracle_query"]}
                if "oracle_query" in row
                else {}
            ),
            **(
                {
                    "canonical_scope_record_ids": copy.deepcopy(
                        row["canonical_scope_record_ids"]
                    ),
                    "allow_complete_scope_superset": True,
                }
                if row.get("allow_complete_scope_superset") is True
                else {}
            ),
            **(
                {
                    "acceptable_query_partitions": copy.deepcopy(
                        row["acceptable_query_partitions"]
                    )
                }
                if "acceptable_query_partitions" in row
                else {}
            ),
            "depends_on": [],
        }
        for row in evidence
    ]
    effect_assertions: list[dict[str, Any]] = []
    readbacks: list[dict[str, Any]] = []
    effect_assertion_ids: dict[str, list[str]] = {}
    for effect_index, effect in enumerate(effects, 1):
        effect_ids = []
        effect_evidence_dependencies = list(
            evidence_dependencies_by_effect.get(effect["id"], [])
        )
        if effect["operation"] == "update":
            for field, expected in effect["patch"].items():
                assertion_id = f"effect-{effect_index:03d}-field-{_slug(str(field))}"
                effect_ids.append(assertion_id)
                effect_assertions.append({
                    "id": assertion_id,
                    "type": "field_equals",
                    "app": effect["app"],
                    "collection": effect["collection"],
                    "record_id": effect["record_id"],
                    "field": field,
                    "expected": copy.deepcopy(expected),
                    "depends_on": effect_evidence_dependencies,
                })
            for field, tokens in effect.get("contains_fields", {}).items():
                assertion_id = (
                    f"effect-{effect_index:03d}-field-"
                    f"{_slug(str(field))}-contains"
                )
                effect_ids.append(assertion_id)
                effect_assertions.append({
                    "id": assertion_id,
                    "type": "field_contains_all",
                    "app": effect["app"],
                    "collection": effect["collection"],
                    "record_id": effect["record_id"],
                    "field": field,
                    "contains_all": copy.deepcopy(tokens),
                    "depends_on": effect_evidence_dependencies,
                })
        elif effect["operation"] == "create":
            assertion_id = f"effect-{effect_index:03d}-record-created"
            effect_ids.append(assertion_id)
            identity_field = (
                runtime_config.get("identity_fields", {})
                .get(effect["app"], {})
                .get(effect["collection"])
            )
            if "record_id_any_of" in effect:
                effect_assertions.append({
                    "id": assertion_id,
                    "type": "record_matches",
                    "app": effect["app"],
                    "collection": effect["collection"],
                    "record_id_any_of": copy.deepcopy(
                        effect["record_id_any_of"]
                    ),
                    "exact_fields": copy.deepcopy(
                        effect["required_patch"]
                    ),
                    "contains_fields": copy.deepcopy(
                        effect.get("contains_fields", {})
                    ),
                    **(
                        {"identity_field": identity_field}
                        if identity_field is not None
                        else {}
                    ),
                    "exact_count": 1,
                    "depends_on": effect_evidence_dependencies,
                })
            else:
                exact_fields = copy.deepcopy(
                    effect["required_patch"]
                )
                if identity_field is not None:
                    exact_fields[identity_field] = str(
                        effect["record_id"]
                    )
                effect_assertions.append({
                    "id": assertion_id,
                    "type": "record_matches",
                    "app": effect["app"],
                    "collection": effect["collection"],
                    "record_id_any_of": [effect["record_id"]],
                    "exact_fields": exact_fields,
                    "contains_fields": copy.deepcopy(
                        effect.get("contains_fields", {})
                    ),
                    **(
                        {"identity_field": identity_field}
                        if identity_field is not None
                        else {}
                    ),
                    "exact_count": 1,
                    "depends_on": effect_evidence_dependencies,
                })
        else:
            assertion_id = f"effect-{effect_index:03d}-message-sent"
            effect_ids.append(assertion_id)
            effect_assertions.append({
                "id": assertion_id,
                "type": "message_exists",
                "app": effect["app"],
                "collection": effect["collection"],
                "server_record_id": effect["record_id"],
                "channel": effect["channel"],
                "contains_all": copy.deepcopy(effect["contains_all"]),
                "exact_count": 1,
                "depends_on": effect_evidence_dependencies,
            })
        effect_assertion_ids[effect["id"]] = list(effect_ids)
        readback = {
            "id": f"effect-{effect_index:03d}-readback",
            "type": "trace_read_after_write",
            "app": effect["app"],
            "collection": effect["collection"],
            "depends_on": effect_ids,
        }
        if effect["operation"] == "send":
            readback["record_id"] = effect["record_id"]
            readback["server_record_id"] = effect["record_id"]
            readback["channel"] = effect["channel"]
            readback["query"] = {"channel": effect["channel"]}
        elif "record_id_any_of" in effect:
            readback["record_id_any_of"] = copy.deepcopy(
                effect["record_id_any_of"]
            )
            readback["exact_fields"] = copy.deepcopy(
                effect["required_patch"]
            )
            readback["contains_fields"] = copy.deepcopy(
                effect.get("contains_fields", {})
            )
        else:
            readback["record_id"] = effect["record_id"]
        readbacks.append(readback)

    # Mutation order is a history property, not a state-assertion dependency.
    # Keep effect assertions dependent only on the evidence that authorizes
    # that effect.  `successful-effect-order-history` below independently
    # rejects a forbidden commit order.  Coupling the two dimensions makes a
    # later, correct post-write readback fail transitively when the records are
    # present but were created in the wrong order.

    explicit_readback_assertions = [
        {
            "id": f"contract-readback-{readback_index:03d}-{_slug(row['id'])}",
            "type": "post_effect_readback",
            "app": row["app"],
            "collection": row["collection"],
            **(
                {"record_id": row["record_id"]}
                if "record_id" in row
                else {"query": copy.deepcopy(row["query"])}
            ),
            **(
                {
                    "equivalent_search_query": copy.deepcopy(
                        row["equivalent_search_query"]
                    )
                }
                if "equivalent_search_query" in row
                else {}
            ),
            "exact_fields": copy.deepcopy(row["exact_fields"]),
            "depends_on": list(
                effect_assertion_ids[row["after_effect_id"]]
            ),
        }
        for readback_index, row in enumerate(required_readbacks, 1)
    ]

    emitted_assertions = []
    for artifact_index, row in enumerate(emitted_artifacts, 1):
        artifact_identity_field = (
            runtime_config.get("identity_fields", {})
            .get(row["artifact"]["app"], {})
            .get(row["artifact"]["collection"])
        )
        emitted_exact_fields = copy.deepcopy(
            row["artifact"]["assertion_fields"]
        )
        if artifact_identity_field is not None:
            emitted_exact_fields[artifact_identity_field] = row[
                "artifact"
            ]["record_id"]
        emitted_assertions.append({
            "id": f"artifact-{artifact_index:03d}-{_slug(row['id'])}",
            "type": "mutation_emitted_artifact",
            "app": row["artifact"]["app"],
            "collection": row["artifact"]["collection"],
            "record_id": row["artifact"]["record_id"],
            "exact_fields": emitted_exact_fields,
            **(
                {"identity_field": artifact_identity_field}
                if artifact_identity_field is not None
                else {}
            ),
            "runtime_fields": copy.deepcopy(
                row["artifact"].get("runtime_fields", {})
            ),
            "producer": copy.deepcopy(row["producer"]),
            "exact_count": 1,
            "depends_on": [],
        })
    typed_relationship_assertions = _typed_relationship_assertions(
        initial_state=initial_state,
        runtime_config=runtime_config,
        effects=effects,
        emitted_artifacts=emitted_artifacts,
    )

    allowed_collection_additions: dict[
        tuple[str, str],
        set[str],
    ] = {}
    inexact_addition_collections: set[tuple[str, str]] = set()
    for effect in effects:
        if effect["operation"] != "create":
            continue
        key = (effect["app"], effect["collection"])
        if effect.get("record_id") is None:
            inexact_addition_collections.add(key)
            continue
        allowed_collection_additions.setdefault(key, set()).add(
            str(effect["record_id"])
        )
    for emitted in emitted_artifacts:
        artifact = emitted["artifact"]
        key = (artifact["app"], artifact["collection"])
        allowed_collection_additions.setdefault(key, set()).add(
            str(artifact["record_id"])
        )
    collection_closure_assertions = []
    for closure_index, (key, additions) in enumerate(
        sorted(allowed_collection_additions.items()),
        start=1,
    ):
        if key in inexact_addition_collections:
            continue
        app, collection = key
        initial_ids = {
            str(record.get("id") or "")
            for record in initial_state[app][collection]
        }
        collection_closure_assertions.append({
            "id": (
                f"collection-closure-{closure_index:03d}-"
                f"{_slug(app)}-{_slug(collection)}"
            ),
            "type": "collection_id_set_equals",
            "app": app,
            "collection": collection,
            "expected_record_ids": sorted(initial_ids | additions),
            "expected_count": len(initial_ids | additions),
            "depends_on": [],
        })
    expected_updates: dict[
        tuple[str, str, str],
        dict[str, Any],
    ] = {}
    expected_addition_rows: dict[
        tuple[str, str],
        list[dict[str, Any]],
    ] = {}
    inexact_state_collections: set[tuple[str, str]] = set(
        inexact_addition_collections
    )
    for effect in effects:
        key = (effect["app"], effect["collection"])
        if effect["operation"] == "update":
            if effect.get("contains_fields"):
                inexact_state_collections.add(key)
                continue
            expected_updates[
                (key[0], key[1], str(effect["record_id"]))
            ] = copy.deepcopy(effect["patch"])
        elif effect["operation"] == "create":
            if (
                effect.get("record_id") is None
                or effect.get("contains_fields")
            ):
                inexact_state_collections.add(key)
                continue
            exact_fields = copy.deepcopy(effect["required_patch"])
            identity_field = (
                runtime_config.get("identity_fields", {})
                .get(key[0], {})
                .get(key[1])
            )
            if identity_field is not None:
                exact_fields[identity_field] = str(effect["record_id"])
            expected_addition_rows.setdefault(key, []).append({
                "record_id": str(effect["record_id"]),
                "exact_fields": exact_fields,
                "runtime_fields": {},
            })
        elif effect["operation"] == "send":
            # A send contract intentionally allows any message containing the
            # authored tokens, so a byte-exact terminal row cannot be compiled
            # without inventing prose.  The message assertion plus exact
            # successful-mutation history still proves one scoped send and no
            # extra mutation.
            inexact_state_collections.add(key)
    for emitted in emitted_artifacts:
        artifact = emitted["artifact"]
        key = (artifact["app"], artifact["collection"])
        emitted_exact_fields = copy.deepcopy(
            artifact["assertion_fields"]
        )
        identity_field = (
            runtime_config.get("identity_fields", {})
            .get(key[0], {})
            .get(key[1])
        )
        if identity_field is not None:
            emitted_exact_fields[identity_field] = str(
                artifact["record_id"]
            )
        expected_addition_rows.setdefault(key, []).append({
            "record_id": str(artifact["record_id"]),
            "exact_fields": emitted_exact_fields,
            "runtime_fields": copy.deepcopy(
                artifact.get("runtime_fields", {})
            ),
        })
    collection_state_assertions = []
    for app, collections in sorted(initial_state.items()):
        for collection, records in sorted(collections.items()):
            key = (app, collection)
            if key in inexact_state_collections:
                continue
            expected_initial_records = copy.deepcopy(records)
            for record in expected_initial_records:
                patch = expected_updates.get(
                    (app, collection, str(record.get("id") or "")),
                    {},
                )
                record.update(copy.deepcopy(patch))
            expected_initial = [
                {
                    "record_id": str(record["id"]),
                    "exact_fields": {
                        str(field): copy.deepcopy(value)
                        for field, value in record.items()
                        if str(field) != "id"
                    },
                    "runtime_fields": {},
                }
                for record in expected_initial_records
            ]
            additions = copy.deepcopy(
                expected_addition_rows.get(key, [])
            )
            collection_state_assertions.append({
                "id": (
                    f"collection-state-{_slug(app)}-"
                    f"{_slug(collection)}"
                ),
                "type": "collection_state_contract",
                "app": app,
                "collection": collection,
                "expected_initial_records": expected_initial,
                "expected_additions": additions,
                "expected_count": len(expected_initial) + len(additions),
                "depends_on": [],
            })

    forbidden_assertions = []
    for row_index, row in enumerate(forbidden, 1):
        for field, expected in row["fields"].items():
            forbidden_assertions.append({
                "id": (
                    f"forbidden-{row_index:03d}-"
                    f"{_slug(row['app'])}-{_slug(row['collection'])}-"
                    f"{_slug(str(field))}"
                ),
                "type": "field_equals",
                "app": row["app"],
                "collection": row["collection"],
                "record_id": row["record_id"],
                "field": field,
                "expected": copy.deepcopy(expected),
                "forbidden_guard": True,
                "depends_on": [],
            })
    budget = {
        "id": "complete-atomic-effect-budget",
        "type": "atomic_effect_budget",
        "app": effects[0]["app"],
        "collection": effects[0]["collection"],
        "expected_effects": copy.deepcopy(effects),
        "depends_on": [],
    }
    expected_history_entries = []
    for effect in effects:
        matching_artifacts = [
            emitted["artifact"]
            for emitted in emitted_artifacts
            if (
                emitted["producer"]["operation"] == effect["operation"]
                and emitted["producer"]["app"] == effect["app"]
                and emitted["producer"]["collection"]
                == effect["collection"]
                and emitted["producer"].get("record_id")
                == effect.get("record_id")
            )
        ]
        expected_history_entries.append({
            "logical_effect_id": effect["id"],
            "mutation_kind": effect["operation"],
            "target_app": effect["app"],
            "target_collection": effect["collection"],
            "primary_native_identity": effect.get("record_id"),
            "emitted_artifact_identities": [
                {
                    "app": artifact["app"],
                    "collection": artifact["collection"],
                    "record_id": artifact["record_id"],
                    "runtime_time_fields": sorted(
                        artifact.get("runtime_fields", {})
                    ),
                }
                for artifact in matching_artifacts
            ],
            "commit_sequence": "successful_trace_order",
            "commit_time": "runtime_utc_for_emitted_artifacts",
        })
    history = {
        "id": "successful-mutation-history-exact",
        "type": "successful_mutation_history_exact",
        "app": effects[0]["app"],
        "collection": effects[0]["collection"],
        "expected_effects": copy.deepcopy(effects),
        "depends_on": [],
    }
    if all(
        (
            effect["operation"] != "update"
            or len(effect.get("patch", {}))
            + len(effect.get("contains_fields", {}))
            == 1
        )
        and (
            effect["operation"] not in {"update", "create"}
            or effect.get("record_id") is not None
        )
        for effect in effects
    ):
        history["expected_history_entries"] = expected_history_entries
        if runtime_config.get("commit_clock_utc") is not None:
            history["release_clock_utc"] = runtime_config[
                "commit_clock_utc"
            ]
    order_history = [
        {
            "id": "successful-effect-order-history",
            "type": "effect_order_history",
            "app": effects[0]["app"],
            "collection": effects[0]["collection"],
            "expected_effects": copy.deepcopy(effects),
            "effect_order_constraints": copy.deepcopy(
                effect_order_constraints
            ),
            "depends_on": [],
        }
    ] if effect_order_constraints else []
    assertions = [
        *evidence_assertions,
        *effect_assertions,
        *([] if explicit_readback_assertions else readbacks),
        *explicit_readback_assertions,
        *emitted_assertions,
        *typed_relationship_assertions,
        *collection_closure_assertions,
        *collection_state_assertions,
        *forbidden_assertions,
        budget,
        history,
        *order_history,
    ]
    task_id = "agentic-" + candidate_sha[:24]
    task = {
        "schema_version": TASK_SCHEMA_VERSION,
        "verification_semantics": VERIFICATION_SEMANTICS,
        "task_id": task_id,
        "domain_label": domain_label,
        "family": "agent_authored_complex_workflow",
        "difficulty": "unrated_pilot",
        "split": "development",
        "evaluation_overlap": False,
        "instruction": student_request,
        "allowed_apps": allowed_apps,
        "app_capabilities": app_capabilities,
        "initial_state": initial_state,
        "api_catalog": catalog,
        "runtime_config": runtime_config,
        "operation_plan": [],
        "assertions": assertions,
        "assertion_dependency_edges": [
            [parent, assertion["id"]]
            for assertion in assertions
            for parent in assertion.get("depends_on", [])
        ],
        "structural_signature": (
            "agent-authored:"
            + hashlib.sha256(
                canonical({
                    "domain": domain_label,
                    "apps": app_capabilities,
                    "effects": [
                        (row["operation"], row["app"], row["collection"])
                        for row in effects
                    ],
                }).encode()
            ).hexdigest()[:24]
        ),
        "generation_provenance": {
            "generator": (
                "benchmark_factory.agentic_runtime_compiler."
                "compile_runtime_source"
            ),
            "source_candidate_relative_path": candidate_relative_path,
            "source_candidate_markdown_sha256": candidate_sha,
            "source_rubric_sha256": rubric_sha256,
            "materializer_source_schema": RUNTIME_SOURCE_SCHEMA,
            "materializer_source_content_sha256": hashlib.sha256(
                canonical(source).encode()
            ).hexdigest(),
            "compiler_made_substantive_task_decisions": False,
            "source_prompts_seen": False,
        },
    }
    # Validate the public docs before hashing the complete task.
    endpoint_catalog(task)
    task["content_sha256"] = hashlib.sha256(
        canonical(task).encode()
    ).hexdigest()
    validate_task(task)
    return task


def compile_runtime_source_file(
    *,
    candidate_path: Path,
    source_path: Path,
    domain_label: str,
    rubric_sha256: str,
    root: Path,
) -> dict[str, Any]:
    candidate = candidate_path.read_text(encoding="utf-8")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    return compile_runtime_source(
        candidate_markdown=candidate,
        candidate_relative_path=(
            candidate_path.resolve().relative_to(root.resolve()).as_posix()
        ),
        source=source,
        domain_label=domain_label,
        rubric_sha256=rubric_sha256,
    )
