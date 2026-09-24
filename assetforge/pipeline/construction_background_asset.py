"""Explicit readable non-target records, independent of app scoring capability.

Ordinary background makes no uncheckable preservation promise. A task may add
native protection assertions where supported; those remain separate obligations.
No business fields are filled with blank/schema defaults by this constructor.
"""
import copy
from .construction_assets import exact, record_id, require, text
from .construction_app_asset import capability


def background_state(params, context, alias):
    exact(params, ['business_context', 'application', 'collection', 'records',
                   'read_paths', 'exclusion_basis'], 'readable background parameters')
    text(params['business_context'], 'background business context')
    app = text(params['application'], 'application')
    collection = text(params['collection'], 'collection')
    basis = text(params['exclusion_basis'], 'business reason these records are outside the target scope')
    entry = capability(app)
    require(collection in entry['entities'], 'unknown background entity collection')
    shape = entry['entities'][collection]
    specs = params['records']
    require(isinstance(specs, list) and 1 <= len(specs) <= 100, 'bounded explicit background records required')
    reads = copy.deepcopy(params['read_paths'])
    require(isinstance(reads, list) and reads, 'explicit native read paths required')
    for read in reads:
        require(isinstance(read, dict) and set(read) <= {'method', 'url', 'params', 'body'}, 'invalid background read')
        require(read.get('method') in ('GET', 'POST'), 'background discovery must use a native read operation')
        text(read.get('url'), 'read URL')
    records, entities = [], {}
    for spec in specs:
        exact(spec, ['entity', 'fields'], 'background record')
        symbol = text(spec['entity'], 'background entity symbol')
        require(symbol not in entities, 'duplicate background entity')
        fields = copy.deepcopy(spec['fields'])
        require(isinstance(fields, dict) and fields, 'meaningful Author fields required')
        require('id' not in fields and set(fields) <= set(shape['fields']), 'unknown or generated background fields')
        require(set(shape['required']) - {'id'} <= set(fields), 'required background business fields missing')
        rid = 'B' + record_id(context['root_task_id'], context['seed'], alias, app, symbol)[:12]
        fields['id'] = rid
        records.append(fields)
        entities[alias + '.' + symbol] = {'id': rid, 'adapter': app, 'collection': [app, collection],
            'record': fields, 'instance_role': 'non_target_background', 'exclusion_basis': basis}
    return {'world': {app: {collection: records}}, 'entities': entities,
            'relations': [], 'reads': reads, 'actions': [], 'writes': [],
            'protected_fields': [], 'assertions': [], 'obligations': ['background_entity_seeded'],
            'obligation_kinds': {'background_entity_seeded': 'structural_background'},
            'background_only': True,
            'capability_semantics': {'preservation': 'task-owned when natively supported',
                'necessary_effect': False, 'semantic_distractor_confirmed': False}}
