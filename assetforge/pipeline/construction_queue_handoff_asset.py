"""`queue_handoff_state` 1.0.0 — self-authored extension: hand a record to another queue/tier.

A handoff is a business structure with two required effects: the record must move to the target
queue/state **and** the handoff must leave an auditable trace (tag or note), while the requester's
original fields stay untouched.  Official applications expose the two halves separately; this asset
pairs them and requires both of the application's own assertions.
"""
from __future__ import annotations

try:  # package import in production
    from .construction_assets import exact, record_id, require, text
    from .construction_field_state_asset import _fill_required
except ImportError:  # identical source shipped flat into the independent native review sandbox
    from construction_assets import exact, record_id, require, text
    from construction_field_state_asset import _fill_required

ADAPTERS = {
    'zendesk': {
        'collection': 'tickets', 'id_field': 'id',
        'seed': {'subject': 'native handoff', 'group_id': '{old_queue}', 'status': 'open',
                 'requester_id': 'native-requester'},
        'world_extra': {'groups': [{'id': '{old_queue}', 'name': 'Tier 1'},
                                   {'id': '{new_queue}', 'name': 'Tier 2'}]},
        'move': {'method': 'PUT', 'url': 'https://acme.zendesk.com/api/v2/tickets/{id}',
                 'body': {'group_id': '{new_queue}'}},
        'trace': {'method': 'PUT', 'url': 'https://acme.zendesk.com/api/v2/tickets/{id}/tags',
                  'body': {'tags': ['{trace_value}']}},
        'move_assertion': {'type': 'zendesk_ticket_group_equals', 'ticket_id': '{id}',
                           'group_id': '{new_queue}'},
        'trace_assertion': {'type': 'zendesk_ticket_has_tag', 'ticket_id': '{id}', 'tag': '{trace_value}'},
        'protected_fields': ['subject'],
    },
    'helpscout': {
        'collection': 'conversations', 'id_field': 'id',
        'seed': {'subject': 'native handoff', 'status': 'active'},
        'move': {'method': 'PATCH', 'url': 'https://api.helpscout.net/v2/conversations/{id}',
                 'body': {'status': 'pending'}},
        'trace': {'method': 'POST',
                  'url': 'https://api.helpscout.net/v2/conversations/{id}/threads/note',
                  'body': {'text': '{trace_value}'}},
        'move_assertion': {'type': 'helpscout_conversation_status_equals',
                           'conversation_id': '{id}', 'status': 'pending'},
        'trace_assertion': {'type': 'helpscout_conversation_has_note',
                            'conversation_id': '{id}', 'body_contains': '{trace_value}'},
        'protected_fields': ['subject'],
    },
    'freshdesk': {
        'collection': 'tickets', 'id_field': 'id',
        'seed': {'subject': 'native handoff', 'status': 2},
        'move': {'method': 'PUT', 'url': 'https://acme.freshdesk.com/api/v2/tickets/{id}',
                 'body': {'priority': 4}},
        'trace': {'method': 'POST', 'url': 'https://acme.freshdesk.com/api/v2/tickets/{id}/notes',
                  'body': {'body': '{trace_value}'}},
        'move_assertion': {'type': 'freshdesk_ticket_exists'},
        'trace_assertion': {'type': 'freshdesk_ticket_has_note', 'body_contains': '{trace_value}'},
        'protected_fields': ['subject'],
    },
    'reamaze': {
        'collection': 'conversations', 'id_field': 'id',
        'seed': {'subject': 'native handoff', 'status': 'unresolved'},
        'move': {'method': 'PATCH', 'url': 'https://native.reamaze.io/api/v1/conversations/{id}',
                 'body': {'conversation': {'status': 'resolved'}}},
        'trace': {'method': 'POST',
                  'url': 'https://native.reamaze.io/api/v1/conversations/{id}/messages',
                  'body': {'message': {'body': '{trace_value}', 'author_type': 'user'}}},
        'move_assertion': {'type': 'reamaze_conversation_exists'},
        'trace_assertion': {'type': 'reamaze_conversation_has_message', 'body_contains': '{trace_value}'},
        'protected_fields': ['subject'],
    },
    'gorgias': {
        'collection': 'tickets', 'id_field': 'id',
        'seed': {'subject': 'native handoff', 'status': 'open'},
        'move': {'method': 'PUT', 'url': 'https://api.gorgias.com/api/tickets/{id}',
                 'body': {'status': 'closed'}},
        'trace': {'method': 'POST', 'url': 'https://api.gorgias.com/api/tickets/{id}/messages',
                  'body': {'body_text': '{trace_value}', 'sender_type': 'agent'}},
        'move_assertion': {'type': 'gorgias_ticket_exists'},
        'trace_assertion': {'type': 'gorgias_ticket_has_message', 'body_contains': '{trace_value}'},
        'protected_fields': ['subject'],
    },
}


def queue_handoff_state(params, context, alias):
    exact(params, ['business_context', 'application', 'target_queue', 'trace_value',
                   'protected_field', 'protected_value'], 'queue_handoff_state parameters')
    text(params['business_context'], 'business context')
    app = text(params['application'], 'application')
    require(app in ADAPTERS, 'unsupported queue-handoff application: ' + str(app))
    spec = ADAPTERS[app]
    queue = text(params['target_queue'], 'target queue')
    trace_value = text(params['trace_value'], 'trace value')
    protected_field = text(params['protected_field'], 'protected field')
    protected_value = text(params['protected_value'], 'protected value')
    require(protected_field in spec['protected_fields'],
            app + ' protects only ' + ', '.join(spec['protected_fields']))
    rid = 'H' + record_id(context['root_task_id'], context['seed'], alias, app, 'handoff')[:12]
    old_queue = 'Q' + record_id(context['root_task_id'], context['seed'], alias, app, 'tier1')[:8]
    new_queue = 'Q' + record_id(context['root_task_id'], context['seed'], alias, app, 'tier2')[:8]
    slot = {'id': rid, 'new_queue': new_queue, 'old_queue': old_queue, 'trace_value': trace_value}

    def fill(value):
        if isinstance(value, dict):
            return {key.format(**slot): fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill(item) for item in value]
        if isinstance(value, str):
            return value.format(**slot)
        return value

    seed = fill(spec['seed'])
    record = _fill_required({'collection': [app, spec['collection']]},
                            {'id': rid, **seed, protected_field: protected_value})
    world = {app: {spec['collection']: [record]}}
    if spec.get('world_extra'):
        world[app].update(fill(spec['world_extra']))
    move = {'method': spec['move']['method'], 'url': spec['move']['url'].format(**slot),
            'body': fill(spec['move']['body'])}
    trace = {'method': spec['trace']['method'], 'url': spec['trace']['url'].format(**slot),
             'body': fill(spec['trace']['body'])}
    return {'world': world,
            'entities': {alias + '.record': {'id': rid, 'adapter': app,
                                             'collection': [app, spec['collection']], 'record': record}},
            'relations': [],
            'reads': [{'method': 'GET', 'url': spec['move']['url'].format(**slot)}],
            'actions': [move, trace],
            'writes': [{'entity': alias + '.record', 'field': 'queue', 'value': queue}],
            'protected_fields': [{'entity': alias + '.record', 'field': protected_field}],
            'assertions': [fill(spec['move_assertion']), fill(spec['trace_assertion'])],
            'obligations': ['handoff_state_recorded', 'handoff_trace_audited',
                            'requester_state_preserved']}
