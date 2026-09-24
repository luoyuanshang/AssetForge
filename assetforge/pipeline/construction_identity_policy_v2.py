"""Explicit schema-bound identity fragments and readable identity-bound policy carriers."""
import copy
from .construction_assets import require, bounded_batch as legacy_batch
from .construction_app_asset import capability
from .construction_linking_adapters import linking_extended as legacy_link, EXTENDED_ADAPTERS, IDENTITY_UNSAFE, NAME_REQUIRED
from .construction_policy_carriers import policy_with_carriers as legacy_policy


def linking_extended(params, context, alias):
    for role in ('source', 'target'):
        side = params[role]; adapter = side['adapter']
        require(adapter in EXTENDED_ADAPTERS and adapter not in IDENTITY_UNSAFE, 'unsupported identity adapter')
        spec = EXTENDED_ADAPTERS[adapter]
        shape = capability(spec['app'])['entities'][spec['path'][1]]
        owned = {spec.get('id_field', 'id'), spec.get('key_field', spec['key'])}
        if spec.get('needs_audience'): owned.add('list_id')
        for record in side['records']:
            fields = record['fields']
            require(isinstance(fields, dict) and not (set(fields) & owned) and set(fields) <= set(shape['fields']),
                    'identity business fields conflict with native schema or generated keys')
            require(set(shape['required']) - owned <= set(fields), 'required identity business fields missing')
            require(adapter not in NAME_REQUIRED or bool(fields.get('name')), 'display name must be supplied by Author')
    part = legacy_link(params, context, alias)
    for symbol, entity in part['entities'].items():
        entity['identity_kind'] = 'seeded_native'
        if entity['adapter'] == 'gmail_messages':
            part['reads'].append({'method': 'GET', 'url': 'gmail/v1/users/me/messages/' + entity['id']})
    return part


def bounded_batch(params, context, alias, prior):
    for symbol in params.get('entity_refs', []):
        require(symbol in prior, 'unresolved batch target')
        entity = prior[symbol]
        require(entity.get('identity_kind') != 'unresolved_creation_output', 'batch requires a bound native record')
        adapter = entity['adapter']
        if adapter == 'hubspot_contacts':
            require(set(params.get('updates', {})) == {'jobtitle'} and params.get('protected_fields') == ['phone'],
                    'this HubSpot batch supports jobtitle and phone preservation')
        else:
            require(adapter == 'slack_users' and set(params.get('updates', {})) == {'status_text'} and
                    params.get('protected_fields') == ['status_emoji'], 'unsupported finite batch adapter or fields')
    return legacy_batch(params, context, alias, prior)


def policy_with_carriers(params, context, alias):
    part = legacy_policy(params, context, alias)
    entity = part['entities'][alias + '.policy']; entity['identity_kind'] = 'seeded_native'
    if params['readable_carrier'] == 'gmail_message_body':
        part['reads'] = [{'method': 'GET', 'url': 'gmail/v1/users/me/messages/' + entity['id']}]
        part['assertions'] += [{'type': 'gmail_message_has_label', 'message_id': entity['id'], 'label_id': label}
                                for label in ('INBOX', 'SENT')]
        part['protected_fields'] += [{'entity': alias + '.policy', 'field': 'label_ids'}]
        part['capability_semantics'] = {'carrier_identity': 'native message ID retained with both original labels',
            'body_match': 'official normalized body containment; message body is not mutable through the pinned update API',
            'business_policy_interpretation': 'Author and independent Reviewer; not decided by the carrier builder'}
    return part
