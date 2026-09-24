"""`approval_decision_state` 1.0.0 — a composed business structure beyond any single official effect.

This is an *extension* asset: the official applications expose either a field/status update or an
append (note/message), never the two as one business structure.  An approval decision, however, is
exactly that: the record's state must move to the decided status **and** the decision reason must be
appended as an auditable note, while the original request fields stay untouched.

Adapters below pair the application's own update route with its own append route and require both of
its assertions to hold (status/field equals + has-note/message), so a task cannot be scored by doing
only half of the business step.
"""
from __future__ import annotations

try:  # package import in production
    from .construction_assets import exact, record_id, require, text
    from .construction_field_state_asset import _fill_required
except ImportError:  # identical source shipped flat into the independent native review sandbox
    from construction_assets import exact, record_id, require, text
    from construction_field_state_asset import _fill_required

ADAPTERS = {
    'helpscout': {
        'collection': 'conversations', 'id_field': 'id', 'seed': {'subject': 'native approval'},
        'update': {'method': 'PATCH',
                   'url': 'https://api.helpscout.net/v2/conversations/{id}',
                   'body': {'status': 'closed'}},
        'append': {'method': 'POST',
                   'url': 'https://api.helpscout.net/v2/conversations/{id}/threads/note',
                   'body': {'text': '{reason}'}},
        'state_assertion': {'type': 'helpscout_conversation_status_equals', 'status': 'closed'},
        'append_assertion': {'type': 'helpscout_conversation_has_note', 'body_contains': '{reason}'},
        'protected_fields': ['subject'],
    },
    'freshdesk': {
        'collection': 'tickets', 'id_field': 'id', 'seed': {'subject': 'native approval'},
        'update': {'method': 'PUT', 'url': 'https://acme.freshdesk.com/api/v2/tickets/{id}',
                   'body': {'status': 5}},
        'append': {'method': 'POST', 'url': 'https://acme.freshdesk.com/api/v2/tickets/{id}/notes',
                   'body': {'body': '{reason}'}},
        'state_assertion': {'type': 'freshdesk_ticket_exists'},
        'append_assertion': {'type': 'freshdesk_ticket_has_note', 'body_contains': '{reason}'},
        'protected_fields': ['subject'],
    },
    'reamaze': {
        'collection': 'conversations', 'id_field': 'id', 'seed': {'subject': 'native approval'},
        'update': {'method': 'PATCH',
                   'url': 'https://native.reamaze.io/api/v1/conversations/{id}',
                   'body': {'conversation': {'status': 'resolved'}}},
        'append': {'method': 'POST',
                   'url': 'https://native.reamaze.io/api/v1/conversations/{id}/messages',
                   'body': {'message': {'body': '{reason}', 'author_type': 'user'}}},
        'state_assertion': {'type': 'reamaze_conversation_exists'},
        'append_assertion': {'type': 'reamaze_conversation_has_message', 'body_contains': '{reason}'},
        'protected_fields': ['subject'],
    },
    'gorgias': {
        'collection': 'tickets', 'id_field': 'id', 'seed': {'subject': 'native approval'},
        'update': {'method': 'PUT', 'url': 'https://api.gorgias.com/api/tickets/{id}',
                   'body': {'status': 'closed'}},
        'append': {'method': 'POST', 'url': 'https://api.gorgias.com/api/tickets/{id}/messages',
                   'body': {'body_text': '{reason}', 'sender_type': 'agent'}},
        'state_assertion': {'type': 'gorgias_ticket_exists'},
        'append_assertion': {'type': 'gorgias_ticket_has_message', 'body_contains': '{reason}'},
        'protected_fields': ['subject'],
    },
    'zoho_desk': {
        'collection': 'tickets', 'id_field': 'id', 'seed': {'subject': 'native approval'},
        'update': {'method': 'PUT', 'url': 'https://desk.zoho.com/api/v1/tickets/{id}',
                   'body': {'status': 'Closed'}},
        'append': {'method': 'POST', 'url': 'https://desk.zoho.com/api/v1/tickets/{id}/comments',
                   'body': {'content': '{reason}'}},
        'state_assertion': {'type': 'zoho_desk_ticket_exists'},
        'append_assertion': {'type': 'zoho_desk_ticket_has_comment', 'body_contains': '{reason}'},
        'protected_fields': ['subject'],
    },
}


def approval_decision_state(params, context, alias):
    exact(params, ['business_context', 'application', 'decision', 'reason',
                   'protected_field', 'protected_value'], 'approval_decision_state parameters')
    text(params['business_context'], 'business context')
    app = text(params['application'], 'application')
    require(app in ADAPTERS, 'unsupported approval-decision application: ' + str(app))
    spec = ADAPTERS[app]
    decision = text(params['decision'], 'decision')
    reason = text(params['reason'], 'reason')
    protected_field = text(params['protected_field'], 'protected field')
    protected_value = text(params['protected_value'], 'protected value')
    require(protected_field in spec['protected_fields'],
            app + ' protects only ' + ', '.join(spec['protected_fields']))
    rid = 'A' + record_id(context['root_task_id'], context['seed'], alias, app, 'approval')[:12]
    record = _fill_required({'collection': [app, spec['collection']]},
                            {'id': rid, **spec['seed'], protected_field: protected_value})
    slot = {'id': rid, 'reason': reason, 'decision': decision}

    def fill(value):
        if isinstance(value, dict):
            return {key.format(**slot): fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill(item) for item in value]
        if isinstance(value, str):
            return value.format(**slot)
        return value

    update = {'method': spec['update']['method'], 'url': spec['update']['url'].format(**slot),
              'body': fill(spec['update']['body'])}
    append = {'method': spec['append']['method'], 'url': spec['append']['url'].format(**slot),
              'body': fill(spec['append']['body'])}
    assertions = [fill(spec['state_assertion']), fill(spec['append_assertion'])]
    return {'world': {app: {spec['collection']: [record]}},
            'entities': {alias + '.record': {'id': rid, 'adapter': app,
                                             'collection': [app, spec['collection']], 'record': record}},
            'relations': [],
            'reads': [{'method': 'GET', 'url': spec['update']['url'].format(**slot)}],
            'actions': [update, append],
            'writes': [{'entity': alias + '.record', 'field': 'decision', 'value': decision}],
            'protected_fields': [{'entity': alias + '.record', 'field': protected_field}],
            'assertions': assertions,
            'obligations': ['decision_state_recorded', 'decision_reason_audited',
                            'protected_request_state']}
