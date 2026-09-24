"""`native_field_state` 1.0.0: turn an official app's own write route into a scored field effect.

Every adapter below is *derived* from the pinned the frozen release sources rather than invented:

  * `inspect_official_app_surfaces.py` reads the official world schema, the API route table and the
    assertion registry, and reports for each application the collections, the mutating routes and
    the field-level assertions;
  * `probe_official_field_writes.py` then tries, natively, to seed one record, prove the field
    assertion fails before the write, execute the application's own documented route and prove the
    assertion passes afterwards.  Only adapters that pass both directions are listed here.

The builder seeds the record with the scored field at an explicit placeholder and the protected
field at its real value, writes the scored field through the official route, and emits field-level
assertions for both cells, so neither is satisfied for free.
"""
from __future__ import annotations

import copy

try:  # package import in production
    from .construction_assets import ROOT, exact, record_id, require, text
except ImportError:  # identical source shipped flat into the independent native review sandbox
    from construction_assets import ROOT, exact, record_id, require, text

PLACEHOLDER = 'unset-native-placeholder'

ADAPTERS = {
    'zoom': {
        'collection': ['zoom', 'meetings'], 'model': 'Meeting', 'id_field': 'id', 'id_key': 'meeting_id',
        'assertion': 'zoom_meeting_field_equals',
        'write': {'method': 'PATCH', 'url': 'zoom/v2/meetings/{id}', 'body_template': {'{field}': '{value}'}},
        'supported_fields': ['topic'],
    },
    'xero': {
        'collection': ['xero', 'invoices'], 'model': 'XeroInvoice', 'id_field': 'invoice_id',
        'id_key': 'invoice_id', 'assertion': 'xero_invoice_field_equals',
        'write': {'method': 'POST', 'url': 'https://api.xero.com/api.xro/2.0/Invoices/{id}',
                  'body_template': {'Reference': '{value}'}},
        'supported_fields': ['reference'],
    },
    'xero_contacts': {
        'collection': ['xero', 'contacts'], 'model': 'XeroContact', 'id_field': 'contact_id',
        'id_key': 'contact_id', 'assertion': 'xero_contact_field_equals',
        'write': {'method': 'POST', 'url': 'https://api.xero.com/api.xro/2.0/Contacts/{id}',
                  'body_template': {'Name': '{value}'}},
        'supported_fields': ['name'],
    },
    'quickbooks': {
        'collection': ['quickbooks', 'invoices'], 'model': 'QBInvoice', 'id_field': 'invoice_id',
        'id_key': 'invoice_id', 'assertion': 'quickbooks_invoice_field_equals',
        'write': {'method': 'POST', 'url': 'https://quickbooks.api.intuit.com/v3/company/{realm}/invoice',
                  'body_template': {'Id': '{id}', 'DocNumber': '{value}'}},
        'supported_fields': ['doc_number'],
    },
    'quickbooks_customers': {
        'collection': ['quickbooks', 'customers'], 'model': 'QBCustomer', 'id_field': 'customer_id',
        'id_key': 'customer_id', 'assertion': 'quickbooks_customer_field_equals',
        'write': {'method': 'POST', 'url': 'https://quickbooks.api.intuit.com/v3/company/{realm}/customer',
                  'body_template': {'Id': '{id}', 'DisplayName': '{value}'}},
        'supported_fields': ['display_name'],
    },
}


def _record(spec, rid, field, value, protected_field, protected_value):
    """Native record: required fields are taken from the official model, never invented."""
    record = {'id': rid}
    record[spec['id_field']] = rid
    record[field] = PLACEHOLDER
    record[protected_field] = protected_value
    return _fill_required(spec, record)


# Our own reconstruction of the official applications: record requirements are materialised in the
# app-capability catalog by build_app_capability_catalog.py, so the asset builders no longer import
# the official package to learn a record shape.
CAPABILITY_CATALOG = ROOT / 'assetforge/artifacts/app_capabilities/catalog.json'
_REQUIREMENTS_CACHE = {}


def _our_requirements():
    if not _REQUIREMENTS_CACHE:
        import json
        catalog = json.loads(CAPABILITY_CATALOG.read_text())
        for app, entry in catalog['applications'].items():
            _REQUIREMENTS_CACHE[app] = entry.get('record_requirements') or {}
    return _REQUIREMENTS_CACHE


def _value_for(kind):
    if kind.startswith('literal:'):
        return kind.split(':', 1)[1].split('|')[0]
    return {'string': '', 'integer': 0, 'number': 0.0, 'boolean': False,
            'array': [], 'object': {}}.get(kind, '')


def _fill_required(spec, record):
    """Complete the record from OUR materialised reconstruction, never from the official package."""
    app, collection = spec['collection'][0], spec['collection'][1]
    requirements = (_our_requirements().get(app) or {}).get(collection)
    require(requirements is not None,
            'application/collection missing from our capability catalog: ' + app + '.' + collection)
    for name, kind in (requirements.get('required') or {}).items():
        if name in record:
            continue
        record[name] = _value_for(kind)
    allowed = set(requirements.get('fields') or [])
    if not allowed:
        return record
    return {key: value for key, value in record.items() if key in allowed}


def native_field_state(params, context, alias):
    exact(params, ['business_context', 'application', 'field', 'value', 'protected_field',
                   'protected_value'], 'native_field_state parameters')
    text(params['business_context'], 'business context')
    app = text(params['application'], 'application')
    require(app in ADAPTERS, 'unsupported native field-state application: ' + str(app))
    spec = ADAPTERS[app]
    field = text(params['field'], 'field')
    protected_field = text(params['protected_field'], 'protected field')
    require(field in spec['supported_fields'],
            app + ' supports only the probed fields ' + ', '.join(spec['supported_fields']))
    require(protected_field != field, 'protected field must differ from the scored field')
    value = text(params['value'], 'value')
    protected_value = text(params['protected_value'], 'protected value')
    require(value != PLACEHOLDER and value != protected_value,
            'scored value must differ from the seeded placeholder and the protected value')
    rid = 'N' + record_id(context['root_task_id'], context['seed'], alias, app, field)[:12]
    realm = 'R' + record_id(context['root_task_id'], context['seed'], alias, app, 'realm')[:10]
    record = _record(spec, rid, field, value, protected_field, protected_value)
    action = {'method': spec['write']['method'],
              'url': spec['write']['url'].format(id=rid, realm=realm),
              'body': {key.format(field=field, value=value, id=rid): val.format(field=field, value=value, id=rid)
                       for key, val in spec['write']['body_template'].items()}}
    assertions = [{'type': spec['assertion'], spec['id_key']: rid, 'field': field, 'value': value},
                  {'type': spec['assertion'], spec['id_key']: rid, 'field': protected_field,
                   'value': protected_value}]
    return {'world': {spec['collection'][0]: {spec['collection'][1]: [record]}},
            'entities': {alias + '.record': {'id': rid, 'adapter': app,
                                             'collection': spec['collection'], 'record': record}},
            'relations': [],
            'reads': [{'method': 'GET', 'url': _read_url(spec, rid, realm)}],
            'actions': [action],
            'writes': [{'entity': alias + '.record', 'field': field, 'value': value}],
            'protected_fields': [{'entity': alias + '.record', 'field': protected_field}],
            'assertions': assertions,
            'obligations': ['scored_field_state', 'protected_sibling_state', 'native_route_effect']}


def _read_url(spec, rid, realm):
    app = spec['collection'][0]
    if app == 'zoom':
        return 'zoom/v2/meetings/' + rid
    if app == 'xero':
        return 'https://api.xero.com/api.xro/2.0/Contacts/' + rid if spec['collection'][1] == 'contacts' \
            else 'https://api.xero.com/api.xro/2.0/Invoices/' + rid
    if app == 'quickbooks':
        return 'https://quickbooks.api.intuit.com/v3/company/' + realm + '/query'
    raise ValueError('no probed read route for ' + app)
