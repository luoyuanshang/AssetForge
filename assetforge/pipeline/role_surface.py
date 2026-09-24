"""Typed semantic roles and split-disjoint synthetic application surfaces."""
from __future__ import annotations

import copy
import hashlib
from typing import Any


LEGACY_ROLE_BY_APP = {
    "RuleVault": "policy_source",
    "CaseFlow": "candidate_store",
    "GridWorks": "identity_roster",
    "SignalPost": "message_sink",
    "ValuePort": "authorization_source",
    "WorkLoom": "artifact_sink",
    "PeopleHarbor": "people_store",
    "PulseDesk": "service_desk",
}
ROLE_CAPABILITIES = {
    "policy_source": ("search", "read"),
    "candidate_store": ("search", "read", "update", "create"),
    "identity_roster": ("search", "read", "update", "create"),
    "message_sink": ("search", "read", "send"),
    "authorization_source": ("search", "read", "update", "create"),
    "artifact_sink": ("search", "read", "update", "create"),
    "people_store": ("search", "read", "update", "create"),
    "service_desk": ("search", "read", "update", "create", "send"),
}
SUPPORTED_OPERATIONS = frozenset(("search", "read", "update", "create", "send"))

# Product-like names deliberately avoid literal role words.  Every split owns
# a disjoint vocabulary, so heldout cannot be solved by memorizing development
# app tokens.  Collection schemas and observed records remain available as the
# legitimate way to infer what each app does.
_SPLIT_NAMES = {
    "development": (
        "Aster", "Brindle", "Cobalt", "Dovetail", "Elara", "Fennel",
        "Gossamer", "Halcyon", "Ibis", "Juno", "Kairo", "Lark",
        "Mica", "Nori", "Oriel", "Pecan", "Quartz", "Ravel",
        "Solace", "Tundra", "Umber", "Vela", "Wren", "Yarrow",
    ),
    "calibration": (
        "Aven", "Bramble", "Cirrus", "Drift", "Esker", "Flint",
        "Ginkgo", "Haven", "Ivory", "Jasper", "Koru", "Linden",
        "Mallow", "Nimbus", "Opal", "Prairie", "Quillan", "Ripple",
        "Saffron", "Thicket", "Upland", "Verge", "Willow", "Zephyr",
    ),
    "heldout": (
        "Alder", "Basin", "Cairn", "Delta", "Elm", "Fjord",
        "Grove", "Hearth", "Inlet", "Jetty", "Knoll", "Lagoon",
        "Mesa", "Nectar", "Oxbow", "Palisade", "Quarry", "Reed",
        "Shoal", "Terrace", "Vale", "Weir", "Xylem", "Yucca",
    ),
}


def surface_pool(split: str, role: str) -> tuple[str, ...]:
    names = _SPLIT_NAMES.get(split)
    if names is None or role not in ROLE_CAPABILITIES:
        raise ValueError(f"unsupported split/role: {split}/{role}")
    # Every role draws from the same neutral vocabulary. A token therefore
    # maps to different roles across tasks and cannot itself reveal semantics.
    return names


def role_apps(task: dict[str, Any]) -> dict[str, str]:
    declared = task.get("app_roles")
    if isinstance(declared, dict) and declared:
        result = {str(role): str(app) for role, app in declared.items()}
        if len(result.values()) != len(set(result.values())):
            raise ValueError("app_roles assigns one surface to multiple roles")
        return result
    allowed = set(map(str, task.get("allowed_apps", [])))
    return {
        role: app for app, role in LEGACY_ROLE_BY_APP.items()
        if app in allowed
    }


def app_for_role(task: dict[str, Any], role: str) -> str:
    apps = role_apps(task)
    if role not in apps:
        raise ValueError(f"task is missing required semantic role: {role}")
    return apps[role]


def capabilities_for_task(task: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    explicit = task.get("app_capabilities")
    if explicit is not None:
        allowed = tuple(dict.fromkeys(map(str, task.get("allowed_apps", []))))
        if (
            not isinstance(explicit, dict)
            or set(map(str, explicit)) != set(allowed)
        ):
            raise ValueError(
                "app_capabilities must exactly cover allowed_apps"
            )
        capabilities: dict[str, tuple[str, ...]] = {}
        for app in allowed:
            operations = explicit.get(app)
            if (
                not isinstance(operations, list)
                or not operations
                or any(
                    not isinstance(operation, str)
                    or operation not in SUPPORTED_OPERATIONS
                    for operation in operations
                )
                or len(operations) != len(set(operations))
            ):
                raise ValueError(
                    f"invalid explicit capabilities for {app}"
                )
            capabilities[app] = tuple(operations)
        # Agent-authored worlds use an exact endpoint-level catalog in
        # addition to these coarse executor capabilities. They intentionally
        # do not pretend that arbitrary applications fit the legacy eight
        # semantic roles.
        if task.get("app_roles") is not None or task.get("app_role_schema") is not None:
            raise ValueError(
                "explicit app_capabilities cannot be mixed with legacy app roles"
            )
        return capabilities

    apps = role_apps(task)
    capabilities = {}
    for role, app in apps.items():
        if role not in ROLE_CAPABILITIES:
            raise ValueError(f"unknown semantic app role: {role}")
        capabilities[app] = ROLE_CAPABILITIES[role]
    allowed = set(map(str, task.get("allowed_apps", [])))
    if set(capabilities) != allowed:
        raise ValueError("typed app roles do not exactly cover allowed_apps")
    schema = task.get("app_role_schema")
    if schema is not None:
        if not isinstance(schema, dict) or set(map(str, schema)) != allowed:
            raise ValueError("app_role_schema does not exactly cover allowed_apps")
        for role, app in apps.items():
            row = schema.get(app)
            if not isinstance(row, dict) or row.get("role") != role:
                raise ValueError(f"app_role_schema role mismatch for {app}")
            if tuple(row.get("capabilities", ())) != ROLE_CAPABILITIES[role]:
                raise ValueError(f"app_role_schema capability mismatch for {app}")
    return capabilities


def _surface_mapping(task_id: str, split: str, legacy_apps: list[str]) -> dict[str, str]:
    pool = surface_pool(split, "policy_source")
    ordered_names = sorted(
        pool,
        key=lambda name: hashlib.sha256(f"{task_id}:{split}:{name}".encode()).hexdigest(),
    )
    ordered_apps = sorted(
        legacy_apps,
        key=lambda app: hashlib.sha256(f"{task_id}:role-position:{app}".encode()).hexdigest(),
    )
    return {app: ordered_names[index] for index, app in enumerate(ordered_apps)}


def permute_task_surfaces(task: dict[str, Any]) -> dict[str, Any]:
    """Return a v4 candidate with role-equivalent, split-specific app names."""
    value = copy.deepcopy(task)
    split = str(value.get("split"))
    original_task_id = str(value.get("task_id"))
    legacy_apps = [str(app) for app in value.get("allowed_apps", [])]
    unknown = [app for app in legacy_apps if app not in LEGACY_ROLE_BY_APP]
    if unknown:
        raise ValueError(f"cannot permute untyped legacy apps: {unknown}")
    mapping = _surface_mapping(original_task_id, split, legacy_apps)
    if len(mapping.values()) != len(set(mapping.values())):
        raise ValueError("surface permutation produced an app-name collision")
    roles = {LEGACY_ROLE_BY_APP[app]: surface for app, surface in mapping.items()}

    value["task_id"] = original_task_id.replace("syn-", "synv4-", 1)
    value["allowed_apps"] = [mapping[app] for app in legacy_apps]
    value["initial_state"] = {mapping[app]: state for app, state in value["initial_state"].items()}
    for row in value.get("operation_plan", []):
        row["app"] = mapping[str(row["app"])]
    for row in value.get("assertions", []):
        row["app"] = mapping[str(row["app"])]
        # Fresh repaired candidates use a hidden exact-effect budget whose
        # nested effect declarations are part of the generator/scorer
        # contract.  Keep those declarations role-equivalent when surfaces
        # are permuted; otherwise the public task would be renamed while the
        # hidden scorer still referred to legacy app labels.
        effects = row.get("expected_effects")
        if isinstance(effects, list):
            for effect in effects:
                if isinstance(effect, dict) and "app" in effect:
                    effect["app"] = mapping[str(effect["app"])]
    instruction = str(value.get("instruction", ""))
    for old, new in mapping.items():
        instruction = instruction.replace(old, new)
    value["instruction"] = instruction
    value["surface_schema_version"] = "typed-split-disjoint-app-surfaces-v1"
    value["app_roles"] = roles
    value["app_role_schema"] = {
        app: {"role": role, "capabilities": list(ROLE_CAPABILITIES[role])}
        for role, app in roles.items()
    }
    value["structural_signature"] = str(value.get("structural_signature")) + ":surface-v4"
    provenance = dict(value.get("generation_provenance") or {})
    provenance.update({
        "surface_transform": "benchmark_factory.role_surface.permute_task_surfaces",
        "surface_source_task_id": original_task_id,
        "surface_split_disjoint": True,
        "surface_role_metadata_visible_to_model": False,
    })
    value["generation_provenance"] = provenance
    value.pop("content_sha256", None)
    return value
