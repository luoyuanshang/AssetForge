"""Hash-checked construction assets and their Author-facing descriptions."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from .construction_assets import ROOT, construct, load_catalog, merge, require

CATALOG = ROOT / "assetforge/artifacts/construction_catalog.json"


class AssetLibrary:
    def __init__(self, path=CATALOG, expected_sha256=None):
        self.path = Path(path)
        self.sha256 = expected_sha256 or hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.catalog = load_catalog(self.path, self.sha256)
        self.entries = {row["id"]: row for row in self.catalog["assets"]}
        require(len(self.entries) == len(self.catalog["assets"]), "ambiguous asset identity")

    def describe(self, ids=None):
        selected = list(self.entries) if ids is None else list(ids)
        unknown = set(selected) - set(self.entries)
        require(not unknown, "unknown assets: " + ", ".join(sorted(unknown)))
        rows = []
        for asset_id in selected:
            entry = self.entries[asset_id]
            rows.append({
                "id": entry["id"], "version": entry["version"],
                "description": (ROOT / entry["description"]["path"]).read_text(),
                "description_path": entry["description"]["path"],
                "definition": json.loads((ROOT / entry["definition"]["path"]).read_text()),
            })
        return rows

    def compose(self, selections, *, task_id, seed, business_time):
        if isinstance(business_time, str) and business_time.endswith("Z"):
            business_time = business_time[:-1] + "+00:00"
        blueprint = {"schema_version": "assetforge-construction-blueprint-v1",
                     "root_task_id": task_id, "seed": seed,
                     "business_time": business_time, "assets": copy.deepcopy(selections)}
        fragments = construct(blueprint, self.catalog)
        return blueprint, {
            key: copy.deepcopy(fragments[key])
            for key in ("world", "assertions", "entities", "relations", "writes",
                        "protected_fields", "asset_bindings", "blueprint_sha256")
        }


def combine_state(base, additional):
    return merge(base, additional)
