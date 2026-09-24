"""Resolve independent decisions against exact, immutable catalog versions.

The native reviewer may use ``name@version`` or separate ``asset_id``/``version``
fields. A family-only answer is unambiguous only in a single-version catalog.
Never expand an unversioned accept across several versions of an asset.
"""
from __future__ import annotations


def versioned_id(asset: dict) -> str:
    name, version = asset.get("id"), asset.get("version")
    if not isinstance(name, str) or not name or "@" in name:
        raise ValueError("catalog asset id must be a nonempty unversioned string")
    if not isinstance(version, str) or not version or "@" in version:
        raise ValueError("catalog asset version must be a nonempty string")
    return name + "@" + version


def normalize_decisions(decision: dict, catalog: dict) -> dict[str, dict]:
    """Return exactly one reasoned decision per catalog entry, or fail closed."""
    expected = {}
    families: dict[str, list[str]] = {}
    for asset in catalog.get("assets", []):
        key = versioned_id(asset)
        if key in expected:
            raise ValueError("duplicate catalog asset version: " + key)
        expected[key] = asset
        families.setdefault(asset["id"], []).append(key)
    if not expected:
        raise ValueError("empty review catalog")
    rows = decision.get("asset_decisions") if isinstance(decision, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("missing per-version asset decisions")
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("asset decision must be an object")
        name = row.get("asset_id")
        if not isinstance(name, str) or not name:
            raise ValueError("asset decision id missing")
        version = row.get("version")
        if "@" in name:
            key = name
            if version is not None and key.rsplit("@", 1)[1] != version:
                raise ValueError("conflicting explicit asset versions: " + name)
        elif version is not None:
            key = versioned_id({"id": name, "version": version})
        else:
            candidates = families.get(name, [])
            if len(candidates) != 1:
                raise ValueError("ambiguous or unknown unversioned asset decision: " + name)
            key = candidates[0]
        if key not in expected:
            raise ValueError("decision outside reviewed catalog: " + key)
        if key in result:
            raise ValueError("duplicate asset decision: " + key)
        if row.get("decision") not in ("accept", "reject"):
            raise ValueError("invalid asset verdict: " + key)
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise ValueError("asset decision reason missing: " + key)
        result[key] = dict(row, asset_id=expected[key]["id"], version=expected[key]["version"])
    missing = expected.keys() - result.keys()
    if missing:
        raise ValueError("missing asset version decisions: " + ", ".join(sorted(missing)))
    return result
