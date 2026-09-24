"""`native_append_effect` 1.0.0: scored note/tag/message appended through the official route.

Adapters are derived from `inspect_official_app_surfaces.py` and proved by
`probe_official_append_effects.py`: the record is seeded from the official model, the application's
own append route executes without error, and the application's own `*_has_*` assertion is false
before the call and true afterwards.  Only adapters that passed both directions are listed.
"""
from __future__ import annotations

import copy

try:  # package import in production
    from .construction_assets import exact, record_id, require, text
    from .construction_field_state_asset import _fill_required
except ImportError:  # identical source shipped flat into the independent native review sandbox
    from construction_assets import exact, record_id, require, text
    from construction_field_state_asset import _fill_required

ADAPTERS = {
    'zendesk': {
        'seed': {'subject': 'native append'}, 'assertion': 'zendesk_ticket_has_tag',
        'body': {'tags': ['{business_value}']},
        'write': {'method': 'PUT', 'url': 'https://acme.zendesk.com/api/v2/tickets/{id}/tags'},
        'assertion_template': {'ticket_id': '{id}', 'tag': '{business_value}'},
    },
    'freshdesk': {
        'seed': {'subject': 'native append'}, 'assertion': 'freshdesk_ticket_has_note',
        'body': {'body': '{business_value}'},
        'write': {'method': 'POST', 'url': 'https://acme.freshdesk.com/api/v2/tickets/{id}/notes'},
        'assertion_template': {'ticket_id': '{id}', 'body_contains': '{business_value}'},
    },
    'helpscout': {
        'seed': {'subject': 'native append'}, 'assertion': 'helpscout_conversation_has_reply',
        'body': {'text': '{business_value}'},
        'write': {'method': 'POST',
                  'url': 'https://api.helpscout.net/v2/conversations/{id}/threads/reply'},
        'assertion_template': {'conversation_id': '{id}', 'body_contains': '{business_value}'},
    },
    'intercom': {
        'seed': {'email': 'native-append@example.org'}, 'assertion': 'intercom_contact_has_note',
        'body': {'body': '{business_value}'},
        'write': {'method': 'POST', 'url': 'https://api.intercom.io/contacts/{id}/notes'},
        'assertion_template': {'contact_id': '{id}', 'body_contains': '{business_value}'},
    },
    'zoho_desk': {
        'seed': {'subject': 'native append'}, 'assertion': 'zoho_desk_ticket_has_comment',
        'body': {'content': '{business_value}'},
        'write': {'method': 'POST', 'url': 'https://desk.zoho.com/api/v1/tickets/{id}/comments'},
        'assertion_template': {'ticket_id': '{id}', 'body_contains': '{business_value}'},
    },
    'reamaze': {
        'seed': {'subject': 'native append'}, 'assertion': 'reamaze_conversation_has_message',
        'body': {'message': {'body': '{business_value}', 'author_type': 'user'}},
        'write': {'method': 'POST', 'url': 'https://native.reamaze.io/api/v1/conversations/{id}/messages'},
        'assertion_template': {'conversation_id': '{id}', 'body_contains': '{business_value}'},
    },
    'gorgias': {
        'seed': {'subject': 'native append'}, 'assertion': 'gorgias_ticket_has_message',
        'body': {'body_text': '{business_value}', 'sender_type': 'agent'},
        'write': {'method': 'POST', 'url': 'https://api.gorgias.com/api/tickets/{id}/messages'},
        'assertion_template': {'ticket_id': '{id}', 'body_contains': '{business_value}'},
    },
}


def native_append_effect(params, context, alias):
    exact(params, ['business_context', 'application', 'business_value', 'protected_field',
                   'protected_value'], 'native_append_effect parameters')
    text(params['business_context'], 'business context')
    app = text(params['application'], 'application')
    require(app in ADAPTERS, 'unsupported native append-effect application: ' + str(app))
    spec = ADAPTERS[app]
    business_value = text(params['business_value'], 'business value')
    protected_field = text(params['protected_field'], 'protected field')
    protected_value = text(params['protected_value'], 'protected value')
    require(business_value != protected_value, 'appended value must differ from the protected value')
    rid = 'P' + record_id(context['root_task_id'], context['seed'], alias, app, 'append')[:12]
    record = _fill_required({'collection': [app, _collection(app)]}, {'id': rid, **spec['seed']})
    require(protected_field in record or protected_field in spec['seed'],
            app + ' protected field is not part of the seeded native record')
    record[protected_field] = protected_value
    slot = {'id': rid, 'business_value': business_value}

    def fill(value):
        if isinstance(value, dict):
            return {key.format(**slot): fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill(item) for item in value]
        if isinstance(value, str):
            return value.format(**slot)
        return value

    action = {'method': spec['write']['method'], 'url': spec['write']['url'].format(**slot),
              'body': fill(copy.deepcopy(spec['body']))}
    assertion = {'type': spec['assertion'], **fill(copy.deepcopy(spec['assertion_template']))}
    return {'world': {app: {_collection(app): [record]}},
            'entities': {alias + '.record': {'id': rid, 'adapter': app, 'record': record}},
            'relations': [],
            'reads': [{'method': 'GET', 'url': spec['write']['url'].format(id=rid)}],
            'actions': [action],
            'writes': [{'entity': alias + '.record', 'field': spec['assertion'], 'value': business_value}],
            'protected_fields': [{'entity': alias + '.record', 'field': protected_field}],
            'assertions': [assertion],
            'obligations': ['scored_append_effect', 'protected_sibling_state', 'native_route_effect']}


def _collection(app):
    return {'zendesk': 'tickets', 'freshdesk': 'tickets', 'helpscout': 'conversations',
            'intercom': 'contacts', 'zoho_desk': 'tickets', 'reamaze': 'conversations',
            'gorgias': 'tickets'}[app]
