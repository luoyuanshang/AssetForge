"""L1 contract-derived asset layer, generated from the pinned official contract face.

Supervisor recommendation (2026-09-14 18:55/18:57/18:59), aligned with the design
doc's two-layer asset model:

* L1 (this module, generated): every official State model with its collections and
  fields, the per-application endpoint ids, and the registered assertion types with
  an explicit strength classification.  It answers "what shapes are legal" and, for
  action-only or assertion-less applications, states outright that they cannot carry
  a scored effect.
* L2 (hand written, elsewhere): business rules, world fragments, protection
  obligations, distractor construction and workflow composition.

Hard boundaries (a violation is fail-closed):

* Only ``schema/*``, ``rubric/assertions/*``, ``tools/api/routes/*`` and
  ``tools/api/schemas/*.jsonc`` may be read.  ``benchmark/domains/*`` holds real
  benchmark task instances and must never be a content source; a test asserts this
  module has no such dependency.
* Generation is deterministic and versioned by the official commit; each record
  carries the SHA256 of every source file it consumed plus the SPDX identifier.
* L1 proves shape legality only.  It is not admission: native positive/negative
  evidence and the independent Reviewer still decide admission.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

SCHEMA = 'automation-contract-derived-assets-v1'
OFFICIAL_VERSION_PREFIX = 'official-the frozen release+'
# Bump when the *derivation* changes rather than the official tree: a corrected
# catalog must be published as a new immutable directory, because immutable_write
# fails closed on a changed artifact.  The suffix must also sort after the bare
# `official-the frozen release+<commit>` directory, which `l1_contract_catalog()` selects by
# lexicographic last, so `_` (0x5f) is used rather than `+` (0x2b).
DERIVATION_REVISION = '_attr2_20260915'
SOURCE_POLICY = {
    'allowed_source_globs': [
        'schema/*.py',
        'rubric/assertions/*.py',
        'tools/api/routes/*.py',
        'tools/api/schemas/*.jsonc',
    ],
    'forbidden_source_globs': ['domains/*', 'domains/**/*'],
    'domains_modules_read': False,
    'benchmark_task_instance_used_as_template': False,
    'license': 'MIT (SPDX-License-Identifier: MIT in every consumed file)',
}
WEAK_ASSERTION_SUFFIXES = ('_action_exists', '_action_not_exists', '_not_exists')
ASSERTION_DECORATOR = re.compile(r'@AssertionRegistry\.register\(\s*["\']([^"\']+)["\']\s*\)')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def official_commit(official_root):
    """Best-effort pinned commit identity for the vendored official tree."""
    for name in ('COMMIT', 'commit.txt', '.commit'):
        candidate = Path(official_root) / name
        if candidate.exists():
            return candidate.read_text().strip()
    head = Path(official_root).parent / '.git' / 'HEAD'
    if head.exists():
        return head.read_text().strip().split('/')[-1]
    return 'unknown'


def _state_models(official_root):
    """Return {app: json_schema} from the official WorldState aggregate."""
    import sys
    # ``official_root`` is the ``benchmark`` package directory; its parent
    # must be importable for ``import benchmark...`` to resolve.
    parent = str(Path(official_root).resolve().parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    from .native_runtime_interface import world_state_type
    WorldState = world_state_type()
    models = {}
    for app, field in WorldState.model_fields.items():
        if app == 'meta':
            continue
        try:
            models[app] = field.annotation.model_json_schema()
        except Exception:
            continue
    return models


def _assertion_registry():
    import sys
    from .native_runtime_interface import assertion_handlers
    return sorted(assertion_handlers())


def _assertion_module_owners(official_root):
    """Return {assertion_type: defining module stem} from rubric/assertions/*.py.

    Ownership must come from the module that registers a handler, not from a
    string prefix on the application name: several applications register singular
    nouns.  Measured on the pinned the frozen release tree, a prefix rule left 26 real
    assertion types owned by no application (``facebook_lead_ad_*``,
    ``facebook_page_*``, ``facebook_conversion_*``, ...), so the L1 catalog
    marked ``facebook_lead_ads``/``facebook_pages``/``facebook_conversions`` as
    ``no_assertions`` and the zero-execution static contract check then rejected
    every task that used their real assertions as
    ``unknown_official_assertion_type`` (contract56o: 309 of 438 compile calls
    died in that check, 260 of them on ``facebook_lead_ads`` alone, and no root
    ever reached an accepted compile).
    """
    owners = {}
    for path in sorted((Path(official_root) / 'rubric' / 'assertions').glob('*.py')):
        for name in ASSERTION_DECORATOR.findall(path.read_text(errors='replace')):
            owners.setdefault(name, path.stem)
    return owners


def _assertion_owner(assertion_type, owners, applications):
    """Owning application for one registered assertion type.

    Prefer the registering module when its stem is an application name; aggregate
    modules (``ops_apps``, ``support_apps``) fall back to the longest
    application-name prefix.
    """
    stem = owners.get(assertion_type)
    if stem in applications:
        return stem
    hits = [app for app in applications
            if assertion_type == app or assertion_type.startswith(app + '_')]
    return max(hits, key=len) if hits else None


def _endpoint_ids(official_root):
    out = {}
    schemas = Path(official_root) / 'tools' / 'api' / 'schemas'
    for path in sorted(schemas.glob('*.jsonc')):
        text = path.read_text(errors='replace')
        ids = re.findall(r'"id"\s*:\s*"([a-z0-9_.\-]+)"', text)
        app = path.stem
        out[app] = sorted({value for value in ids if value.startswith(app + '.') or '.' in value})
    return out


def assertion_strength(assertion_type):
    return 'weak' if assertion_type.endswith(WEAK_ASSERTION_SUFFIXES) else 'strong'


def build_catalog(official_root, *, write_root=None):
    official_root = Path(official_root)
    models = _state_models(official_root)
    registered = _assertion_registry()
    owners = _assertion_module_owners(official_root)
    endpoints = _endpoint_ids(official_root)
    version = OFFICIAL_VERSION_PREFIX + official_commit(official_root) + DERIVATION_REVISION

    sources = {}
    for pattern in SOURCE_POLICY['allowed_source_globs']:
        for path in sorted(official_root.glob(pattern)):
            sources[str(path.relative_to(official_root))] = digest(path)

    records = {}
    for app, schema in sorted(models.items()):
        properties = schema.get('properties') or {}
        collections = {}
        for name, spec in properties.items():
            if not isinstance(spec, dict):
                continue
            item = spec.get('items') if spec.get('type') == 'array' else None
            entry = {'type': spec.get('type')}
            if isinstance(item, dict):
                entry['item_properties'] = sorted((item.get('properties') or {}).keys())
                entry['item_required'] = sorted(item.get('required') or [])
            collections[str(name)] = entry
        types = [value for value in registered
                 if _assertion_owner(value, owners, models) == app]
        strengths = {value: assertion_strength(value) for value in types}
        strong = sorted(value for value, kind in strengths.items() if kind == 'strong')
        record = {
            'app': app,
            'version': version,
            'collections': collections,
            'collection_count': len(collections),
            'endpoint_ids': endpoints.get(app, []),
            'endpoint_count': len(endpoints.get(app, [])),
            'assertion_types': sorted(types),
            'assertion_strength': strengths,
            'strong_assertion_types': strong,
            'weak_assertion_types': sorted(value for value, kind in strengths.items() if kind == 'weak'),
            'extra_forbid': bool(schema.get('additionalProperties') is False),
            # Explicit capability class: action-only or assertion-less applications
            # must never be the scored landing point of a cell.
            'capability_tier': ('strong_scorer' if strong else
                                'weak_action_only' if types else 'no_assertions'),
            'may_carry_scored_effect': bool(strong),
            'source_policy': SOURCE_POLICY,
        }
        records[app] = record

    catalog = {
        'schema_version': SCHEMA,
        'official_version': version,
        'official_root': str(official_root),
        'source_policy': SOURCE_POLICY,
        'source_hashes': sources,
        'applications': records,
        'counts': {
            'state_models': len(records),
            'applications_with_endpoints': sum(1 for row in records.values() if row['endpoint_ids']),
            'registered_assertion_types': len(registered),
            'total_collections': sum(row['collection_count'] for row in records.values()),
            'strong_scorer_apps': sum(1 for row in records.values() if row['capability_tier'] == 'strong_scorer'),
            'weak_action_only_apps': sorted(row['app'] for row in records.values()
                                            if row['capability_tier'] == 'weak_action_only'),
            'no_assertion_apps': sorted(row['app'] for row in records.values()
                                        if row['capability_tier'] == 'no_assertions'),
        },
    }
    if write_root is not None:
        write_catalog(catalog, write_root)
    return catalog


def write_catalog(catalog, write_root):
    from .construction_assets import immutable_write
    write_root = Path(write_root)
    write_root.mkdir(parents=True, exist_ok=True)
    for app, record in sorted(catalog['applications'].items()):
        immutable_write(write_root / 'applications' / (app + '.json'), record)
    immutable_write(write_root / 'catalog.json', catalog)
    return write_root / 'catalog.json'


def static_contract_check(task_source, catalog, *, construction_bindings=None):
    """Zero-execution contract pre-check.

    Supervisor recommendation (18:57): a spelling-level error must not cost a full
    official regression.  This phase validates the official vocabulary, endpoint ids
    and assertion types plus the binding shape using only the L1 catalog.
    """
    diagnostics = []
    applications = catalog.get('applications') or {}
    if not isinstance(task_source, dict):
        return [{'error_type': 'ValueError', 'message': 'task_source must be an object'}]

    initial_state = task_source.get('initial_state') or {}
    for app, body in (initial_state.items() if isinstance(initial_state, dict) else []):
        record = applications.get(app)
        if record is None:
            diagnostics.append({'error_type': 'unknown_world_state_app', 'app': app,
                                'closest': difflib_close(app, sorted(applications))})
            continue
        allowed = set(record['collections'])
        for collection in (body or {}):
            if collection == 'actions':
                continue
            if collection not in allowed:
                diagnostics.append({'error_type': 'unknown_world_state_collection',
                                    'app': app, 'collection': collection,
                                    'available': sorted(allowed),
                                    'closest': difflib_close(collection, sorted(allowed))})

    endpoints = set()
    for record in applications.values():
        endpoints.update(record['endpoint_ids'])
    for index, action in enumerate(task_source.get('oracle_actions') or []):
        if not isinstance(action, dict):
            diagnostics.append({'error_type': 'oracle_action_shape', 'index': index})
            continue
        url = str(action.get('url') or '')
        endpoint_id = str(action.get('endpoint_id') or '')
        if endpoint_id and endpoint_id not in endpoints:
            diagnostics.append({'error_type': 'unknown_official_endpoint_id', 'index': index,
                                'endpoint_id': endpoint_id,
                                'closest': difflib_close(endpoint_id, sorted(endpoints))})
        if not url and not endpoint_id:
            diagnostics.append({'error_type': 'oracle_action_missing_endpoint', 'index': index})

    registered = set()
    for record in applications.values():
        registered.update(record['assertion_types'])
    for index, assertion in enumerate(task_source.get('assertions') or []):
        if not isinstance(assertion, dict):
            diagnostics.append({'error_type': 'assertion_shape', 'index': index})
            continue
        kind = str(assertion.get('type') or '')
        if kind not in registered:
            diagnostics.append({'error_type': 'unknown_official_assertion_type', 'index': index,
                                'assertion_type': kind,
                                'closest': difflib_close(kind, sorted(registered))})

    if construction_bindings is not None:
        if not isinstance(construction_bindings, list):
            diagnostics.append({'error_type': 'construction_bindings_not_array'})
        else:
            for index, row in enumerate(construction_bindings):
                if not isinstance(row, dict):
                    diagnostics.append({'error_type': 'construction_binding_shape', 'index': index})
                    continue
                if set(row) != {'obligation_id', 'requirement', 'public_basis',
                                'assertion_indices', 'case_ids'}:
                    diagnostics.append({'error_type': 'construction_binding_shape', 'index': index,
                                        'expected': ['obligation_id', 'requirement', 'public_basis',
                                                     'assertion_indices', 'case_ids'],
                                        'actual': sorted(row)})
    return diagnostics


def difflib_close(value, choices, n=5, cutoff=0.4):
    import difflib
    return difflib.get_close_matches(str(value), [str(item) for item in choices], n=n, cutoff=cutoff)


# Bounds for the author-supplied collections, taken from the schema the Author is
# actually shown rather than from a hand-picked number.
#
# Measured 2026-09-15 (user challenge about the per-case cap): one native construction case costs
# 0.8 ms for the small shape and 17 ms for the schema maximum (64 action replays), so a
# full 64-case submission costs 1.10 s of local native execution -- the previous
# `native_construction_cases<=16` protected against ~20 ms while binding on the Author's
# natural shape: of the run3/run4 rejections it produced, ALL 21 landed at submitted
# 17/18/19/20/22 against limit 16, and 16 contradicted the tool schema the Author reads
# (`native_construction_cases` advertises `maxItems: 64`).  A hidden cap below the
# published bound is a pipeline defect, not a cost control.
#
# Cost is not the binding constraint; provider latency is.  The only defensible caps are
# the published ones:
#   * native_construction_cases: the array schema's own maxItems (64)
#   * policy_fixtures: the profile's strict_maximum_policy_fixtures (already the schema max)
#   * forbidden_extra_actions: no schema maximum exists, so bound it with the sibling
#     arrays' upper bound (64) instead of an invented 16
SCHEMA_ARRAY_MAXIMUM = 64


def static_cost_caps(task_source, profile=None):
    """Report author-supplied collections that exceed their *published* bounds."""
    diagnostics = []
    if not isinstance(task_source, dict):
        return diagnostics
    limits = {'native_construction_cases': SCHEMA_ARRAY_MAXIMUM,
              'forbidden_extra_actions': SCHEMA_ARRAY_MAXIMUM}
    maximum = (profile or {}).get('strict_maximum_policy_fixtures')
    if isinstance(maximum, int) and maximum > 0:
        limits['policy_fixtures'] = maximum
    for key, limit in sorted(limits.items()):
        rows = task_source.get(key)
        if isinstance(rows, list) and len(rows) > limit:
            diagnostics.append({
                'error_type': 'fixture_cost_cap_exceeded',
                'field': key,
                'submitted': len(rows),
                'limit': limit,
                'fix': ('reduce %s to at most %d entries; that is the bound the tool schema '
                        'advertises' % (key, limit)),
            })
    return diagnostics
