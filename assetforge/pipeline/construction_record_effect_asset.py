"""Explicit bounded record updates for previously seed-only application delegates.

Only identities and wire-format projections are generated. Author supplies every
business record, target, initial value and final value. Sibling records remain
non-targets and their update field is protected by the application's predicate.
"""
import copy
import hashlib
from .construction_assets import exact, record_id, require, text
from .construction_app_asset import capability

ADAPTERS = {
    'salesforce': ('contacts', 'department'),
    'hubspot': ('contacts', 'jobtitle'),
    'slack': ('channels', 'topic'),
    'mailchimp': ('subscribers', 'status'),
    'gmail': ('messages', 'label_ids'),
}


def record_effect(params, context, alias):
    exact(params, ['business_context', 'application', 'records', 'target_entity',
                   'value', 'protected_fields', 'scope_name'], 'application record effect')
    text(params['business_context'], 'business context')
    app = text(params['application'], 'application')
    require(app in ADAPTERS, 'unsupported bounded record effect')
    collection, field = ADAPTERS[app]
    target = text(params['target_entity'], 'target entity')
    value = text(params['value'], 'target value')
    scope = text(params['scope_name'], 'scope name')
    specs = params['records']
    require(isinstance(specs, list) and 2 <= len(specs) <= 100, 'explicit target and non-target records required')
    protected = params['protected_fields']
    require(isinstance(protected, list) and len(protected) == len(set(protected)), 'unique protected fields required')
    require(field not in protected, 'cannot preserve the complete field being updated')
    require(app != 'gmail' or not protected,
            'Gmail adapter protects non-target label membership only; it cannot promise arbitrary message fields')
    require(app != 'slack' or not protected,
            'Slack adapter protects non-target topics only; extra protected fields need separate task assertions')
    require(app != 'mailchimp' or set(protected) <= {'email'}, 'subscriber audience is bound by generated scope; only email is an additional protection field')
    definition = capability(app)['entities'][collection]
    scope_id = 'S' + record_id(context['root_task_id'], context['seed'], alias, app, 'scope')[:12]
    entities, rows, identities = {}, [], set()
    for entry in specs:
        exact(entry, ['entity', 'fields'], 'record specification')
        symbol = text(entry['entity'], 'record symbol')
        require(symbol not in entities, 'duplicate record symbol')
        data = copy.deepcopy(entry['fields'])
        require(isinstance(data, dict) and 'id' not in data, 'explicit fields cannot override generated identity')
        require(set(data) <= set(definition['fields']), 'unknown native record fields')
        require(field in data and all(k in data for k in protected), 'initial and protected fields must be explicit')
        rid = 'R' + record_id(context['root_task_id'], context['seed'], alias, app, symbol)[:12]
        if app == 'mailchimp':
            email = text(data.get('email'), 'subscriber email')
            require('@' in email, 'subscriber email required')
            require('list_id' not in data, 'audience identity is generated from the scope')
            rid = hashlib.md5(email.lower().encode()).hexdigest()
            data['list_id'] = scope_id
        if app == 'gmail':
            require(isinstance(data[field], list) and value not in data[field], 'label target must not already be present')
        require(set(definition['required']) <= (set(data) | {'id'}), 'required business fields missing')
        data['id'] = rid
        require(rid not in identities, 'records collide on native identity')
        identities.add(rid)
        rows.append(data)
        entities[symbol] = {'id': rid, 'adapter': app, 'collection': [app, collection], 'record': data,
                            'instance_role': 'target_effect' if symbol == target else 'non_target_background'}
    require(target in entities, 'target not found')
    record = entities[target]['record']; rid = entities[target]['id']
    require(record[field] != value, 'target effect is already satisfied')
    world = {app: {collection: rows}}
    if app == 'gmail':
        world[app]['labels'] = [{'id': scope_id, 'name': value}]
        action = {'method': 'POST', 'url': 'gmail/v1/users/me/messages/' + rid + '/modify',
                  'body': {'addLabelIds': [scope_id]}}
        reads = [{'method': 'GET', 'url': 'gmail/v1/users/me/messages/' + r['id']} for r in rows]
    elif app == 'mailchimp':
        require(value in {'subscribed', 'unsubscribed', 'cleaned', 'pending', 'transactional', 'archived'},
                'invalid native subscription status')
        world[app]['audiences'] = [{'id': scope_id, 'name': scope}]
        action = {'method': 'PATCH', 'url': 'https://us1.api.mailchimp.com/3.0/lists/' + scope_id + '/members/' + rid,
                  'body': {'status': value}}
        reads = [{'method': 'GET', 'url': 'https://us1.api.mailchimp.com/3.0/lists/' + scope_id + '/members'}]
    elif app == 'slack':
        action = {'method': 'POST', 'url': 'slack/conversations.setTopic', 'body': {'channel': rid, 'topic': value}}
        reads = [{'method': 'GET', 'url': 'slack/conversations.list'}]
    elif app == 'hubspot':
        action = {'method': 'PATCH', 'url': 'hubspot/crm/v3/objects/contacts/' + rid,
                  'body': {'properties': {'jobtitle': value}}}
        reads = [{'method': 'GET', 'url': 'hubspot/crm/v3/objects/contacts'}]
    else:
        action = {'method': 'PATCH', 'url': 'https://example.invalid/services/data/v1/sobjects/Contact/' + rid,
                  'body': {'Department': value}}
        reads = [{'method': 'GET', 'url': 'https://example.invalid/services/data/v1/query',
                  'params': {'q': 'SELECT Id, LastName, Email, Department FROM Contact'}}]

    def assertion(row, key, expected):
        if app == 'gmail':
            return {'type': 'gmail_message_has_label', 'message_id': row['id'], 'label_id': expected}
        if app == 'mailchimp':
            return {'type': 'mailchimp_subscriber_exists', 'email': row['email'], 'list_id': scope_id, key: expected}
        if app == 'slack':
            return {'type': 'slack_channel_topic_equals', 'channel': row['id'], 'topic': expected}
        if app == 'hubspot':
            return {'type': 'hubspot_contact_property_equals', 'contact_id': row['id'], 'property': key, 'value': expected}
        return {'type': 'salesforce_contact_field_equals', 'contact_id': row['id'], 'field': key, 'value': expected}

    assertions = [assertion(record, field, scope_id if app == 'gmail' else value)]
    protected_refs = []
    for symbol, entity in entities.items():
        row = entity['record']
        for key in protected:
            assertions.append(assertion(row, key, row[key]))
            protected_refs.append({'entity': alias + '.' + symbol, 'field': key})
        if symbol != target:
            if app == 'gmail':
                assertions.append({'type': 'gmail_message_missing_label', 'message_id': row['id'], 'label_id': scope_id})
                assertions.extend(assertion(row, field, label) for label in row[field])
            else:
                assertions.append(assertion(row, field, row[field]))
            protected_refs.append({'entity': alias + '.' + symbol, 'field': field})
    return {'world': world, 'entities': {alias + '.' + key: row for key, row in entities.items()},
            'relations': [], 'reads': reads, 'actions': [action], 'assertions': assertions,
            'writes': [{'entity': alias + '.' + target, 'field': field, 'value': value}],
            'protected_fields': protected_refs,
            'obligations': ['bounded_record_effect', 'non_target_preservation', 'native_discoverability']}
