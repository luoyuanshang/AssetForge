"""Versioned business fragments, explicit Author choices and deterministic binding.

This module knows native field layouts, not the task's business policy. An asset
returns world fragments and obligations; it never returns a complete question.
"""
from __future__ import annotations
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = ROOT / 'assetforge/artifacts/construction_assets'
SCHEMA = 'assetforge-construction-blueprint-v1'

# The runtime identifier every asset and catalog in this repository is bound to.
# It comes from the neutral runtime interface (see native_runtime_interface.py), so an
# operator running a different runtime build re-pins it in one place.
from .native_runtime_interface import runtime_pin
COMMIT = runtime_pin()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def require(test, message):
    if not test:
        raise ValueError(message)


def exact(value, keys, label):
    require(isinstance(value, dict) and set(value) == set(keys), label + ' requires exactly ' + ','.join(keys))


def text(value, label):
    require(isinstance(value, str) and bool(value.strip()), label + ' must be an explicit nonempty string')
    return value


def immutable_write(path, value):
    """Atomic publication; identical recovery is idempotent, drift fails closed."""
    import os
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (canonical(value) + '\n').encode()
    if path.exists():
        require(path.read_bytes() == raw, 'immutable construction artifact changed: ' + str(path))
        return
    temp = path.with_name(path.name + f'.{os.getpid()}.partial')
    with temp.open('xb') as handle:
        handle.write(raw); handle.flush(); os.fsync(handle.fileno())
    try:
        os.link(temp, path)
    except FileExistsError:
        require(path.read_bytes() == raw, 'concurrent construction publication mismatch')
    finally:
        temp.unlink()


def record_id(root, seed, alias, role, entity):
    return digest([root, seed, alias, role, entity])[:18]


ADAPTERS = {
    'hubspot_contacts': {'app': 'hubspot', 'path': ['hubspot', 'contacts'], 'key': 'email',
                         'read': {'method': 'GET', 'url': 'hubspot/crm/v3/objects/contacts'}},
    'salesforce_contacts': {'app': 'salesforce', 'path': ['salesforce', 'contacts'], 'key': 'email',
                           'read': {'method': 'GET', 'url': 'https://example.invalid/services/data/v1/query',
                                    'params': {'q': 'SELECT Id, Email, FirstName, LastName, Department, NdaStatus FROM Contact'}}},
    'bamboohr_employees': {'app': 'bamboohr', 'path': ['bamboohr', 'actions', 'employee'], 'key': 'workEmail',
                           'read': {'method': 'GET', 'url': 'bamboohr/v1/employees/directory'}},
    'slack_users': {'app': 'slack', 'path': ['slack', 'users'], 'key': 'email',
                    'read': {'method': 'GET', 'url': 'slack/users.list'}},
}


def merge(left, right):
    """Merge disjoint fragments; duplicate identities must be byte-equivalent."""
    if isinstance(left, dict) and isinstance(right, dict):
        out = copy.deepcopy(left)
        for key, value in right.items():
            out[key] = merge(out[key], value) if key in out else copy.deepcopy(value)
        return out
    if isinstance(left, list) and isinstance(right, list):
        out = copy.deepcopy(left)
        for value in right:
            same = [x for x in out if isinstance(x, dict) and isinstance(value, dict)
                    and x.get('id') is not None and x.get('id') == value.get('id')]
            if same:
                require(len(same) == 1 and same[0] == value, 'conflicting native identity fragments')
            elif value not in out:
                out.append(copy.deepcopy(value))
        return out
    require(left == right, 'conflicting scalar asset fragments')
    return copy.deepcopy(left)


def nested(path, value):
    for key in reversed(path):
        value = {key: value}
    return value


def linking(params, context, alias):
    exact(params, ['business_context', 'match_semantics', 'source', 'target'], 'customer_link parameters')
    text(params['business_context'], 'business context')
    require(params['match_semantics'] == 'exact_email_unique', 'v1 only supports explicit exact unique email identity')
    world, entities, keys, reads = {}, {}, {}, []
    for role in ('source', 'target'):
        spec = params[role]
        exact(spec, ['adapter', 'records'], role)
        require(spec['adapter'] in ADAPTERS, 'unsupported identity adapter')
        adapter = ADAPTERS[spec['adapter']]
        require(isinstance(spec['records'], list) and 2 <= len(spec['records']) <= 100, 'identity records range is 2..100')
        rows = []; seen_entities = set(); keymap = {}
        for item in spec['records']:
            exact(item, ['entity', 'business_key', 'fields'], 'identity record')
            entity = text(item['entity'], 'entity'); key = text(item['business_key'], 'business_key')
            require(entity not in seen_entities and key not in keymap, 'ambiguous identity or duplicate entity')
            require(key == key.strip() and key == key.lower() and '@' in key,
                    'exact-email v1 uses canonical lowercase email; aliases/normalization require another asset')
            seen_entities.add(entity)
            fields = copy.deepcopy(item['fields'])
            require(isinstance(fields, dict), 'record fields must be explicit')
            forbidden = {'id', 'employee_id', 'created_at', 'updated_at', 'created_date', 'last_modified_date', adapter['key']}
            require(not (set(fields) & forbidden), 'Author fields collide with asset-owned identity or time')
            rid = record_id(context['root_task_id'], context['seed'], alias, role, entity)
            if spec['adapter'] == 'bamboohr_employees':
                body = dict(fields, employee_id=rid, workEmail=key)
                row = {'id': rid, 'action_key': 'employee', 'params': body, 'created_at': context['business_time']}
            else:
                row = dict(fields, id=rid, email=key)
                times = (('created_at', 'updated_at') if spec['adapter'] == 'hubspot_contacts' else
                         ('created_date', 'last_modified_date') if spec['adapter'] == 'salesforce_contacts' else ())
                row.update({name: context['business_time'] for name in times})
            rows.append(row)
            symbol = f'{alias}.{role}.{entity}'
            entities[symbol] = {'id': rid, 'adapter': spec['adapter'], 'collection': adapter['path'],
                                'business_key': key, 'record': row}
            keymap[key] = symbol
        rows.sort(key=lambda r: digest([context['seed'], alias, role, r['id']]))
        world = merge(world, nested(adapter['path'], rows))
        keys[role] = keymap; reads.append(adapter['read'])
    require(params['source']['adapter'] != params['target']['adapter'], 'link asset requires different native applications')
    require(keys['source'].keys() == keys['target'].keys(), 'unmatched identity unsupported in unique-pair asset v1')
    relations = [{'source': keys['source'][key], 'target': keys['target'][key], 'business_key': key}
                 for key in sorted(keys['source'])]
    return {'world': world, 'entities': entities, 'relations': relations, 'reads': reads,
            'writes': [], 'protected_fields': [], 'assertions': [], 'actions': [],
            'obligations': ['stable_identity', 'source_preservation', 'wrong_customer_result', 'native_discoverability']}


def policy(params, context, alias):
    exact(params, ['business_context', 'channel_name', 'title', 'scope', 'rule', 'exception', 'precedence', 'protected'], 'policy parameters')
    for key in ('business_context', 'channel_name', 'title', 'scope', 'rule', 'exception', 'precedence'):
        text(params[key], key)
    require(params['protected'] is True, 'read-only policy asset requires explicit policy preservation')
    require(params['precedence'] == 'exception_over_rule', 'unsupported rule precedence')
    require(params['rule'] != params['exception'], 'exception must differ from base rule')
    require(re.fullmatch(r'[a-z0-9][a-z0-9_-]{1,70}', params['channel_name']) is not None, 'invalid readable channel name')
    rid = 'C' + record_id(context['root_task_id'], context['seed'], alias, 'policy', 'channel')[:10]
    content = '\n'.join([params['title'], 'Scope: ' + params['scope'], 'Rule: ' + params['rule'],
                         'Exception (takes precedence): ' + params['exception']])
    row = {'id': rid, 'name': params['channel_name'], 'topic': content, 'created': context['business_time']}
    return {'world': {'slack': {'channels': [row]}},
            'entities': {alias + '.policy': {'id': rid, 'adapter': 'slack_channel', 'collection': ['slack', 'channels'], 'record': row}},
            'relations': [], 'reads': [{'method': 'GET', 'url': 'slack/conversations.list'}],
            'writes': [], 'protected_fields': [{'entity': alias + '.policy', 'field': 'topic'}],
            'assertions': [{'type': 'slack_channel_topic_equals', 'channel': rid, 'topic': content}], 'actions': [],
            'obligations': ['readable_policy', 'exception_changes_result', 'policy_preservation', 'legal_alternative']}


def bounded_batch(params, context, alias, prior):
    exact(params, ['business_context', 'entity_refs', 'updates', 'protected_fields', 'public_scope'], 'batch parameters')
    text(params['business_context'], 'business context'); text(params['public_scope'], 'public scope')
    refs = params['entity_refs']
    require(isinstance(refs, list) and 1 <= len(refs) <= 100 and len(set(refs)) == len(refs), 'finite unique batch targets required')
    require(isinstance(params['updates'], dict) and params['updates'], 'explicit nonempty field updates required')
    require(isinstance(params['protected_fields'], list) and params['protected_fields'], 'explicit finite protection fields required')
    require(not (set(params['updates']) & set(params['protected_fields'])), 'write/protection conflict')
    require(not (set(params['updates']) & {'id', 'email', 'employee_id', 'created_at', 'updated_at'}), 'identity manufacture forbidden')
    actions, assertions, writes, protected = [], [], [], []
    for symbol in refs:
        require(symbol in prior, 'unresolved batch entity: ' + str(symbol))
        entity = prior[symbol]
        require(entity['adapter'] in ('hubspot_contacts', 'slack_users'), 'unsupported native finite-batch adapter')
        row = entity['record']; rid = entity['id']
        if entity['adapter'] == 'slack_users':
            require(set(params['updates']) == {'status_text'} and params['protected_fields'] == ['status_emoji'],
                    'Slack v1 writes status_text and preserves status_emoji; other fields unsupported')
            actions.append({'method': 'POST', 'url': 'slack/users.profile.set',
                            'body': {'user': rid, 'profile': copy.deepcopy(params['updates'])}})
        else:
            actions.append({'method': 'PATCH', 'url': 'hubspot/crm/v3/objects/contacts/' + rid,
                            'body': {'properties': copy.deepcopy(params['updates'])}})
        def assertion(key, value):
            if entity['adapter'] == 'slack_users':
                return {'type': 'slack_user_status_equals', 'user': rid,
                        'status_text': params['updates']['status_text'], key: value}
            return {'type': 'hubspot_contact_has_property', 'contact_id': rid, 'property': key, 'value': value}
        for key, value in params['updates'].items():
            require(value is not None and isinstance(value, (str, int, float, bool)), 'batch values must be native observable scalars')
            old = row.get(key, row.get('properties', {}).get(key))
            require(old != value, 'batch update must change the business value')
            writes.append({'entity': symbol, 'field': key, 'value': value})
            assertions.append(assertion(key, value))
        for key in params['protected_fields']:
            require(key in row or key in row.get('properties', {}), 'protected field absent from bound entity')
            value = row.get(key, row.get('properties', {}).get(key))
            require(value is not None, 'null-preservation needs a distinct native assertion contract')
            protected.append({'entity': symbol, 'field': key})
            assertions.append(assertion(key, value))
    return {'world': {}, 'entities': {}, 'relations': [], 'reads': [], 'actions': actions, 'assertions': assertions,
            'writes': writes, 'protected_fields': protected,
            'obligations': ['bounded_scope', 'required_effect', 'non_target_preservation', 'wrong_scope_result', 'legal_alternative']}


BUILDERS = {'customer_link': linking, 'readable_policy_exception': policy, 'bounded_contact_batch': bounded_batch}

# Version-aware builder table.  Frozen 1.0.x entries are absent on purpose so `_version_builder`
# falls back to BUILDERS for them and their behaviour cannot drift; newer admitted versions point at
# their own module (the asset descriptions, not this table, decide what each version offers).
VERSION_BUILDERS = {
    ('native_create_effect', '1.2.0'):
        ('assetforge.pipeline.construction_create_effect_asset_v3', 'native_create_effect'),
    ('app_linkedin', '1.2.0'):
        ('assetforge.pipeline.construction_create_effect_asset_v3', 'native_create_effect'),
    ('customer_link', '1.3.0'):
        ('assetforge.pipeline.construction_identity_policy_v2', 'linking_extended'),
    ('bounded_contact_batch', '1.1.0'):
        ('assetforge.pipeline.construction_identity_policy_v2', 'bounded_batch'),
    ('readable_policy_exception', '1.2.0'):
        ('assetforge.pipeline.construction_identity_policy_v2', 'policy_with_carriers'),
    ('audit_archive_state', '1.1.0'):
        ('assetforge.pipeline.construction_business_extensions_v2', 'audit_archive_state'),
    ('reconciliation_adjustment', '1.1.0'):
        ('assetforge.pipeline.construction_business_extensions_v2', 'reconciliation_adjustment'),
    ('native_field_state', '1.1.0'):
        ('assetforge.pipeline.construction_field_state_asset_v2', 'native_field_state'),
    ('native_create_effect', '1.1.0'):
        ('assetforge.pipeline.construction_create_effect_asset_v2', 'native_create_effect'),
    ('native_discovered_effect', '1.1.0'):
        ('assetforge.pipeline.construction_discovered_effect_asset_v2', 'native_discovered_effect'),
    ('native_append_effect', '1.1.0'):
        ('assetforge.pipeline.construction_append_effect_asset_v2', 'native_append_effect'),
    ('approval_decision_state', '1.1.0'):
        ('assetforge.pipeline.construction_support_workflows_v2', 'approval_decision_state'),
    ('queue_handoff_state', '1.1.0'):
        ('assetforge.pipeline.construction_support_workflows_v2', 'queue_handoff_state'),
    ('application_record_effect', '1.0.0'):
        ('assetforge.pipeline.construction_record_effect_asset', 'record_effect'),
    ('readable_background_records', '1.0.0'):
        ('assetforge.pipeline.construction_background_asset', 'background_state'),
    ('readable_policy_exception', '1.1.0'):
        ('assetforge.pipeline.construction_policy_carriers', 'policy_with_carriers'),
    ('customer_link', '1.2.0'):
        ('assetforge.pipeline.construction_linking_adapters', 'linking_extended'),
    ('native_field_state', '1.0.0'):
        ('assetforge.pipeline.construction_field_state_asset', 'native_field_state'),
    ('native_create_effect', '1.0.0'):
        ('assetforge.pipeline.construction_create_effect_asset', 'native_create_effect'),
    ('native_append_effect', '1.0.0'):
        ('assetforge.pipeline.construction_append_effect_asset', 'native_append_effect'),
    ('native_discovered_effect', '1.0.0'):
        ('assetforge.pipeline.construction_discovered_effect_asset', 'native_discovered_effect'),
    ('approval_decision_state', '1.0.0'):
        ('assetforge.pipeline.construction_approval_decision_asset', 'approval_decision_state'),
    ('reconciliation_adjustment', '1.0.0'):
        ('assetforge.pipeline.construction_reconciliation_adjustment_asset', 'reconciliation_adjustment'),
    ('queue_handoff_state', '1.0.0'):
        ('assetforge.pipeline.construction_queue_handoff_asset', 'queue_handoff_state'),
    ('audit_archive_state', '1.0.0'):
        ('assetforge.pipeline.construction_audit_archive_asset', 'audit_archive_state'),
    ('sheet_row_state', '1.0.0'):
        ('assetforge.pipeline.construction_sheet_row_asset', 'sheet_row_state'),
    # 1.0.1 revisions are the opt-in schema-checked constructors.  They were catalogued as
    # "declared by construction_checked_assets.py" while the version-aware constructor still
    # dispatched them to the frozen 1.0.0 builders, so the declared increment was never reachable.
    # They are wired here so that "declared implementation" and "actually imported implementation"
    # are the same module.
    ('customer_link', '1.0.1'):
        ('assetforge.pipeline.construction_checked_assets', 'linking'),
    ('bounded_contact_batch', '1.0.1'):
        ('assetforge.pipeline.construction_checked_assets', 'bounded_batch'),
}


def _version_builder(asset_id, version):
    target = VERSION_BUILDERS.get((asset_id, version))
    if not target:
        if asset_id.startswith('app_') and version in ('1.1.0', '1.2.0'):
            from .construction_app_asset_v2 import app_state
            return app_state
        # Per-application assets (`app_<application>`) share one implementation module: the asset
        # identity is the application, so no per-application dispatch table is needed.
        if asset_id.startswith('app_') and version == '1.0.0':
            import importlib
            module = importlib.import_module('assetforge.pipeline.construction_app_asset')
            return module.app_state
        return BUILDERS[asset_id]
    import importlib
    module = importlib.import_module(target[0])
    return getattr(module, target[1])


def load_catalog(path, expected_sha256):
    raw = Path(path).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected_sha256, 'frozen asset catalog drift')
    catalog = json.loads(raw)
    require(catalog['schema_version'] in ('assetforge-construction-catalog-v1',
                                         'automation-construction-catalog-v1'), 'unknown catalog version')
    require(catalog['runtime_commit'] == COMMIT, 'incompatible catalog runtime')
    verified = {}
    def verify(ref, label):
        source = (ROOT / ref['path']).resolve(); source.relative_to(ROOT)
        if source not in verified: verified[source] = hashlib.sha256(source.read_bytes()).hexdigest()
        require(verified[source] == ref['sha256'], label + ' drift: ' + ref['path'])
    if 'dependency_contract' in catalog:
        require(catalog['dependency_contract'] in ('asset-import-closure-v1', 'asset-construction-closure-v2') and catalog.get('dependencies'),
                'unknown or empty asset dependency closure')
        for ref in catalog['dependencies']: verify(ref, 'asset dependency')
    for ref in catalog.get('dependencies', []):
        if ref.get('frozen_content'):
            require(ref['frozen_content']['sha256'] == ref['sha256'], 'frozen asset source identity mismatch')
            verify(ref['frozen_content'], 'recoverable asset source')
    for item in catalog['assets']:
        for name in ('definition', 'description', 'implementation'):
            verify(item[name], 'asset ' + name)
        definition = json.loads((ROOT / item['definition']['path']).read_text())
        require(definition['id'] == item['id'] and definition['version'] == item['version'], 'asset identity mismatch')
        require(definition['runtime_commit'] == COMMIT, 'incompatible asset runtime')
    return catalog


def construct(blueprint, catalog):
    exact(blueprint, ['schema_version', 'root_task_id', 'seed', 'business_time', 'assets'], 'blueprint')
    require(blueprint['schema_version'] == SCHEMA, 'unknown construction blueprint')
    text(blueprint['root_task_id'], 'root identity')
    require(type(blueprint['seed']) is int, 'explicit integer seed required')
    business_time = datetime.fromisoformat(blueprint['business_time'])
    require(business_time.tzinfo is not None, 'business time requires explicit timezone')
    definitions = {(x['id'], x['version']): x for x in catalog['assets']}
    require(isinstance(blueprint['assets'], list) and 1 <= len(blueprint['assets']) <= 12, 'composition size 1..12')
    result = {'world': {}, 'entities': {}, 'relations': [], 'reads': [], 'actions': [], 'assertions': [],
              'writes': [], 'protected_fields': [], 'obligations': [], 'asset_bindings': []}
    seen = set()
    for selection in blueprint['assets']:
        exact(selection, ['id', 'version', 'alias', 'reason', 'parameters'], 'asset selection')
        alias = text(selection['alias'], 'asset alias'); text(selection['reason'], 'Author business choice')
        require(re.fullmatch(r'[a-z][a-z0-9_]{0,31}', alias) is not None and alias not in seen, 'duplicate or invalid alias')
        seen.add(alias)
        require((selection['id'], selection['version']) in definitions, 'unfrozen asset version')
        # Version-aware dispatch: frozen 1.0.x versions keep their existing builders byte-for-byte,
        # while a catalog may admit a newer version whose builder lives in its own module.
        definition = definitions[(selection['id'], selection['version'])]
        if selection['id'].startswith('app_'):
            require(selection['parameters'].get('application') == selection['id'][4:],
                    'per-application asset identity differs from selected adapter')
        declared = json.loads((ROOT / definition['definition']['path']).read_text())
        allowed_adapters = declared.get('supported_adapters')
        if allowed_adapters is not None:
            require(selection['parameters'].get('application') in allowed_adapters,
                    'adapter outside frozen asset declaration')
        if declared.get('supported_background_collections'):
            require(selection['parameters'].get('collection') in declared['supported_background_collections'].get(
                selection['parameters'].get('application'), []), 'background collection outside frozen native coverage')
        builder = _version_builder(selection['id'], selection['version'])
        if (definition.get('asset_role') == 'background_distractor' and
                selection['id'].startswith('app_') and selection['version'] == '1.0.0'):
            # Role dispatch: a background/distractor asset may only seed world state; its builder is
            # never the scored-effect builder even though both share the per-application module.
            import importlib
            builder = importlib.import_module(
                'assetforge.pipeline.construction_app_asset').background_state
        part = (builder(selection['parameters'], blueprint, alias, result['entities'])
                if selection['id'] == 'bounded_contact_batch' else builder(selection['parameters'], blueprint, alias))
        if declared.get('applications'):
            require(set(part['world']) <= set(declared['applications']), 'constructed app outside asset declaration')
        result['world'] = merge(result['world'], part['world'])
        require(not (result['entities'].keys() & part['entities'].keys()), 'duplicate entity symbol')
        result['entities'].update(part['entities'])
        for key in ('relations', 'reads', 'actions', 'assertions', 'writes', 'protected_fields'):
            result[key].extend(part[key])
        for obligation in part['obligations']:
            row = {'id': alias + '.' + obligation, 'asset_id': selection['id'], 'alias': alias}
            kind = part.get('obligation_kinds', {}).get(obligation)
            if kind is not None:
                require(kind == 'structural_background' and part.get('background_only') is True and
                        not any(part[k] for k in ('actions', 'writes', 'assertions')),
                        'invalid structural background obligation')
                row.update(kind=kind, entity_symbols=sorted(part['entities']), reads=copy.deepcopy(part['reads']))
            result['obligations'].append(row)
        binding = {'selection': copy.deepcopy(selection), 'definition': definitions[(selection['id'], selection['version'])],
                   'fragment_sha256': digest(part)}
        if part.get('capability_semantics'):
            binding['capability_semantics'] = copy.deepcopy(part['capability_semantics'])
        result['asset_bindings'].append(binding)
    effects = {}
    for effect in result['writes']:
        key = (effect['entity'], effect['field'])
        require(key not in effects or effects[key] == effect['value'], 'conflicting composed writes')
        effects[key] = effect['value']
    for protected in result['protected_fields']:
        require((protected['entity'], protected['field']) not in effects, 'composed write/protection conflict')
    result['blueprint_sha256'] = digest(blueprint)
    return result


def resolve_symbols(value, entities):
    if isinstance(value, dict):
        if set(value) == {'$entity'}:
            require(value['$entity'] in entities, 'unresolved native identity symbol')
            entity = entities[value['$entity']]
            require(entity.get('identity_kind') != 'unresolved_creation_output',
                    'created output has no bound native ID; use a supported native lookup or terminal effect')
            require(entity.get('id'), 'entity has no reusable native identity')
            return entity['id']
        return {k: resolve_symbols(v, entities) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_symbols(v, entities) for v in value]
    return value
