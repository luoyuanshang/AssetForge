"""Native field changes with explicit Author initial records and real identity keys."""
import copy
from .construction_assets import exact, record_id, require, text
from .construction_field_state_asset import ADAPTERS, _our_requirements


def native_field_state(params, context, alias):
    exact(params, ['business_context', 'application', 'field', 'value', 'protected_field',
                   'initial_fields'], 'native field parameters')
    text(params['business_context'], 'business context')
    adapter = text(params['application'], 'field adapter')
    require(adapter in ADAPTERS, 'unknown field adapter')
    spec = ADAPTERS[adapter]; app, collection = spec['collection']
    field = text(params['field'], 'updated field'); value = text(params['value'], 'target value')
    protected = text(params['protected_field'], 'protected field')
    require(field in spec['supported_fields'] and protected != field, 'unsupported or conflicting fields')
    record = copy.deepcopy(params['initial_fields'])
    shape = _our_requirements()[app][collection]
    identity_key = spec['id_field'] if spec['id_field'] in shape['fields'] else 'id'
    require(isinstance(record, dict) and not ({'id', identity_key} & set(record)), 'identities are generated')
    require(set(record) <= set(shape['fields']) and set(shape['required']) - {identity_key} <= set(record),
            'unknown or missing native business fields')
    require(field in record and protected in record and record[field] != value and record[protected] is not None,
            'explicit distinct initial value and protected value required')
    rid = 'N' + record_id(context['root_task_id'], context['seed'], alias, adapter, field)[:12]
    realm = 'R' + record_id(context['root_task_id'], context['seed'], alias, app, 'realm')[:10]
    record[identity_key] = rid
    action = {'method': spec['write']['method'],
        'url': spec['write']['url'].format(id=rid, realm=realm),
        'body': {key.format(field=field, value=value, id=rid): item.format(field=field, value=value, id=rid)
                 for key, item in spec['write']['body_template'].items()}}
    if app == 'quickbooks':
        read = {'method': 'GET', 'url': 'https://quickbooks.api.intuit.com/v3/company/' + realm + '/query',
                'params': {'query': 'select * from ' + ('Invoice' if collection == 'invoices' else 'Customer')}}
    else:
        read = {'method': 'GET', 'url': action['url']}
    return {'world': {app: {collection: [record]}},
        'entities': {alias + '.record': {'id': rid, 'identity_kind': 'seeded_native', 'adapter': app,
            'collection': [app, collection], 'record': record}},
        'relations': [], 'reads': [read], 'actions': [action],
        'writes': [{'entity': alias + '.record', 'field': field, 'value': value}],
        'protected_fields': [{'entity': alias + '.record', 'field': protected}],
        'assertions': [{'type': spec['assertion'], spec['id_key']: rid, 'field': field, 'value': value},
                       {'type': spec['assertion'], spec['id_key']: rid, 'field': protected, 'value': record[protected]}],
        'obligations': ['scored_field_state', 'protected_sibling_state', 'native_route_effect']}
