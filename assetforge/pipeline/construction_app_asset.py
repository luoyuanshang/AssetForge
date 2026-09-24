"""One construction asset per official application, backed by our own capability catalog.

`build_app_assets.py` materialises `artifact:app_<application>@1.0.0` for every application of the
pinned package, using the reconstruction in `artifacts/app_capabilities/catalog.json` (entities,
required/allowed fields, read/write routes, strong/weak assertions) plus the adapter tables that were
probed natively.  This module is the single shared implementation those per-application definitions
point at: the asset identity is the application, not one narrow effect shape.

Effect selection per application, fail-closed:

  * `create`  — the application's own create route flips its existence assertion (probed);
  * `field`   — the application's own update route flips a field-level assertion (probed);
  * `append`  — the application's own append route flips a has-note/tag/message assertion (probed);
  * `seed`    — only for applications whose pinned route table has no mutating route (declared).

Applications without any registered assertion (`mailbox_app`) are materialised too, but as
`background_only`: they can be seeded into a task world and are declared unscoreable.
"""
from __future__ import annotations

try:  # package import in production
    from .construction_assets import ROOT, exact, record_id, require, text
    from .construction_field_state_asset import _fill_required
except ImportError:  # identical source shipped flat into the independent native review sandbox
    from construction_assets import ROOT, exact, record_id, require, text
    from construction_field_state_asset import _fill_required

CAPABILITY_CATALOG = ROOT / 'assetforge/artifacts/app_capabilities/catalog.json'
_CATALOG_CACHE = {}


def capability(app):
    if not _CATALOG_CACHE:
        import json
        _CATALOG_CACHE.update(json.loads(CAPABILITY_CATALOG.read_text())['applications'])
    require(app in _CATALOG_CACHE, 'application missing from our capability catalog: ' + str(app))
    return _CATALOG_CACHE[app]


def _adapter_tables():
    """Adapter rows discovered and proved natively, keyed by application."""
    tables = {}
    try:
        from .construction_discovered_effect_asset import ADAPTERS as discovered
        for app, spec in discovered.items():
            tables.setdefault(app, []).append({
                'shape': 'discovered', 'spec': spec, 'weak': spec.get('weak', False)})
    except ImportError:  # pragma: no cover - sandbox layout
        pass
    try:
        from .construction_create_effect_asset import ADAPTERS as create
        for app, spec in create.items():
            tables.setdefault(app, []).append({'shape': 'create', 'spec': spec, 'weak': False})
    except ImportError:  # pragma: no cover
        pass
    try:
        from .construction_append_effect_asset import ADAPTERS as append
        for app, spec in append.items():
            tables.setdefault(app, []).append({'shape': 'append', 'spec': spec, 'weak': False})
    except ImportError:  # pragma: no cover
        pass
    try:
        from .construction_field_state_asset import ADAPTERS as fields
        for key, spec in fields.items():
            app = 'quickbooks' if key.startswith('quickbooks') else ('xero' if key.startswith('xero') else 'zoom')
            tables.setdefault(app, []).append({'shape': 'field', 'spec': spec, 'weak': False})
    except ImportError:  # pragma: no cover
        pass
    return tables


def app_state(params, context, alias):
    exact(params, ['business_context', 'application', 'business_value'], 'app_state parameters')
    text(params['business_context'], 'business context')
    app = text(params['application'], 'application')
    business_value = text(params['business_value'], 'business value')
    entry = capability(app)
    require(entry['coverage_status'] not in ('no-assertion', 'background-only'),
            app + ' is a background/distractor application in the pinned release; use background_state')
    candidates = _adapter_tables().get(app) or []
    if not candidates:
        return _seed_only_effect(app, entry, business_value, params, context, alias)
    chosen = candidates[0]
    if chosen['shape'] == 'discovered':
        from .construction_discovered_effect_asset import ADAPTERS as discovered, native_discovered_effect
        require(app in discovered, 'discovered effect not registered for ' + app)
        return native_discovered_effect({'business_context': params['business_context'],
                                         'application': app, 'business_value': business_value},
                                        context, alias)
    if chosen['shape'] == 'create':
        from .construction_create_effect_asset import native_create_effect
        return native_create_effect({'business_context': params['business_context'], 'application': app,
                                     'business_value': business_value, 'scope': 'native',
                                     'protected_scope': 'native-protected'}, context, alias)
    if chosen['shape'] == 'append':
        from .construction_append_effect_asset import native_append_effect
        return native_append_effect({'business_context': params['business_context'], 'application': app,
                                     'business_value': business_value,
                                     'protected_field': 'subject', 'protected_value': 'native-protected'},
                                    context, alias)
    if chosen['shape'] == 'field':
        from .construction_field_state_asset import native_field_state
        spec = chosen['spec']
        return native_field_state({'business_context': params['business_context'],
                                   'application': _field_key(app, spec), 'field': spec['supported_fields'][0],
                                   'value': business_value, 'protected_field': _protected(app, spec),
                                   'protected_value': 'native-protected'}, context, alias)
    from .construction_discovered_effect_asset import ADAPTERS as discovered, native_discovered_effect
    require(app in discovered, 'seeded effect not registered for ' + app)
    return native_discovered_effect({'business_context': params['business_context'], 'application': app,
                                     'business_value': business_value}, context, alias)


def _seed_only_effect(app, entry, business_value, params, context, alias):
    """Apps whose library coverage comes from another asset shape.

    The per-application asset still exposes a usable shape for world construction: it seeds the
    application's primary collection from our reconstructed field table.  Where the application's
    own effect is already carried by a dedicated asset (policy carrier, identity link, bounded batch,
    sheet row, seeded state), that asset is recorded as the delegate and no assertion is invented
    here — the effect stays with the asset that proved it natively.
    """
    collections = sorted(entry['entities'])
    require(collections, app + ' has no world collection to seed')
    collection = collections[0]
    rid = 'P' + record_id(context['root_task_id'], context['seed'], alias, app, collection)[:12]
    record = {'id': rid}
    for key in ('name', 'title', 'subject', 'summary', 'reference', 'display_name'):
        record[key] = business_value
        break
    record = _fill_required({'collection': [app, collection]}, record)
    delegates = [binding['asset'] for binding in (entry.get('our_asset_bindings') or [])]
    return {'world': {app: {collection: [record]}},
            'entities': {alias + '.record': {'id': rid, 'adapter': app,
                                             'collection': [app, collection], 'record': record}},
            'relations': [], 'reads': [], 'actions': [], 'writes': [], 'protected_fields': [],
            'assertions': [],
            'obligations': ['application_entity_seeded'],
            'delegated_effect': delegates}


def _field_key(app, spec):
    from .construction_field_state_asset import ADAPTERS
    for key, value in ADAPTERS.items():
        if value is spec:
            return key
    return app


def _protected(app, spec):
    return {'zoom': 'agenda', 'xero': 'currency_code', 'xero_contacts': 'contact_status',
            'quickbooks': 'customer_name', 'quickbooks_customers': 'email',
            'intercom': 'email'}.get(app, 'subject')


def background_state(params, context, alias):
    """Applications the pinned release cannot score: seed their entity and declare it unscoreable."""
    exact(params, ['business_context', 'application', 'collection'], 'background_state parameters')
    app = text(params['application'], 'application')
    collection = text(params['collection'], 'collection')
    entry = capability(app)
    require(entry['coverage_status'] in ('no-assertion', 'background-only'),
            app + ' has assertions; use app_state instead of background_state')
    require(collection in entry['entities'], app + ' has no collection ' + collection)
    rid = 'G' + record_id(context['root_task_id'], context['seed'], alias, app, collection)[:12]
    record = _fill_required({'collection': [app, collection]}, {'id': rid})
    return {'world': {app: {collection: [record]}},
            'entities': {alias + '.record': {'id': rid, 'adapter': app,
                                             'collection': [app, collection], 'record': record}},
            'relations': [], 'reads': [], 'actions': [], 'writes': [], 'protected_fields': [],
            'assertions': [],
            'obligations': ['background_entity_seeded'],
            'background_only': True}
