"""Explicit support state transitions with two independently scored effects.

Author chooses both initial and final business state. The compiler performs no
approval-policy inference. The unchanged subject is bound to the same native
record as the transition and the note. Version 1.0.0 remains historical evidence.
"""
from __future__ import annotations
import copy
from .construction_assets import exact, record_id, require, text
from .construction_field_state_asset import _fill_required
from .construction_approval_decision_asset import ADAPTERS as APPROVAL_RECIPES
from .construction_queue_handoff_asset import ADAPTERS as HANDOFF_RECIPES


APPROVAL_APPLICATIONS = tuple(APPROVAL_RECIPES)
HANDOFF_APPLICATIONS = ('zendesk', 'freshdesk', 'helpscout', 'reamaze', 'gorgias')


def _fill(value, slots):
    if isinstance(value, dict):
        return {key: _fill(item, slots) for key, item in value.items()}
    if isinstance(value, list):
        return [_fill(item, slots) for item in value]
    return value.format(**slots) if isinstance(value, str) else value


def _record_assertion(app, rid, **fields):
    conversation = app in ('helpscout', 'reamaze')
    noun = 'conversation' if conversation else 'ticket'
    return {'type': app + '_' + noun + '_exists', noun + '_id': rid, **fields}


def _output(app, alias, rid, collection, record, actions, assertions, writes, obligations):
    first_url = actions[0]['url']
    end = first_url.index('/' + rid) + (len(rid) + 1 if app in ('zendesk', 'freshdesk') else 0)
    return {'world': {app: {collection: [record]}},
            'entities': {alias + '.record': {'id': rid, 'adapter': app,
                                             'collection': [app, collection], 'record': record}},
            'relations': [], 'reads': [{'method': 'GET', 'url': first_url[:end]}],
            'actions': actions, 'assertions': assertions,
            'writes': [{'entity': alias + '.record', 'field': field, 'value': value}
                       for field, value in writes.items()],
            'protected_fields': [{'entity': alias + '.record', 'field': 'subject'}],
            'obligations': obligations}


def approval_decision_state(params, context, alias):
    exact(params, ['business_context', 'application', 'decision', 'initial_status', 'target_status',
                   'reason', 'protected_field', 'protected_value'], 'approval_decision_state parameters')
    text(params['business_context'], 'business context')
    app = text(params['application'], 'application')
    require(app in APPROVAL_APPLICATIONS, 'unsupported approval application')
    require(params['protected_field'] == 'subject', 'approval protects the explicit subject')
    subject = text(params['protected_value'], 'protected subject')
    decision = text(params['decision'], 'decision')
    reason = text(params['reason'], 'reason')
    before, after = params['initial_status'], params['target_status']
    require(type(before) in (str, int) and type(after) is type(before) and before != after,
            'explicit distinct native initial_status and target_status required')
    spec = APPROVAL_RECIPES[app]
    rid = 'A' + record_id(context['root_task_id'], context['seed'], alias, app, 'approval')[:12]
    record = _fill_required({'collection': [app, spec['collection']]},
                            {'id': rid, 'subject': subject, 'status': before})
    slots = {'id': rid, 'reason': decision + ': ' + reason}
    update = _fill(copy.deepcopy(spec['update']), slots)
    update['body'] = {'conversation': {'status': after}} if app == 'reamaze' else {'status': after}
    note = _fill(copy.deepcopy(spec['append']), slots)
    note_assertion = _fill(copy.deepcopy(spec['append_assertion']), slots)
    if app == 'zoho_desk':
        note_assertion['content_contains'] = note_assertion.pop('body_contains')
    identity = 'conversation_id' if app in ('helpscout', 'reamaze') else 'ticket_id'
    note_assertion[identity] = rid
    assertions = [_record_assertion(app, rid, status=after), note_assertion,
                  _record_assertion(app, rid, subject=subject)]
    return _output(app, alias, rid, spec['collection'], record, [update, note], assertions,
                   {'status': after}, ['decision_state_recorded', 'decision_reason_audited', 'protected_request_state'])


def queue_handoff_state(params, context, alias):
    exact(params, ['business_context', 'application', 'initial_queue', 'target_queue',
                   'trace_value', 'protected_field', 'protected_value'], 'queue_handoff_state parameters')
    text(params['business_context'], 'business context')
    app = text(params['application'], 'application')
    require(app in HANDOFF_APPLICATIONS, 'unsupported native handoff application')
    before = text(params['initial_queue'], 'initial queue identity')
    after = text(params['target_queue'], 'target queue identity')
    require(before != after, 'handoff must change native queue identity')
    require(params['protected_field'] == 'subject', 'handoff protects the explicit subject')
    subject = text(params['protected_value'], 'protected subject')
    trace_value = text(params['trace_value'], 'trace value')
    spec = HANDOFF_RECIPES[app]
    rid = 'H' + record_id(context['root_task_id'], context['seed'], alias, app, 'handoff')[:12]
    field = {'helpscout': 'mailbox_id', 'reamaze': 'category', 'gorgias': 'tags'}.get(app, 'group_id')
    initial_value = [before] if app == 'gorgias' else before
    target_value = [after] if app == 'gorgias' else after
    record = _fill_required({'collection': [app, spec['collection']]},
                            {'id': rid, 'subject': subject, field: initial_value})
    slots = {'id': rid, 'new_queue': after, 'old_queue': before, 'trace_value': trace_value}
    move = _fill(copy.deepcopy(spec['move']), slots)
    move['body'] = {field: target_value}
    if app == 'reamaze': move['body'] = {'conversation': move['body']}
    trace = _fill(copy.deepcopy(spec['trace']), slots)
    trace_assertion = _fill(copy.deepcopy(spec['trace_assertion']), slots)
    identity = 'conversation_id' if app in ('helpscout', 'reamaze') else 'ticket_id'
    trace_assertion[identity] = rid
    state_assertion = _record_assertion(app, rid, **{('tag' if app == 'gorgias' else field): after})
    assertions = [state_assertion, trace_assertion,
                  _record_assertion(app, rid, subject=subject)]
    if app == 'gorgias':
        assertions.append({'type': 'gorgias_ticket_not_exists', 'ticket_id': rid, 'tag': before})
    result = _output(app, alias, rid, spec['collection'], record, [move, trace], assertions,
                     {field: target_value}, ['handoff_state_recorded', 'handoff_trace_audited', 'requester_state_preserved'])
    result['capability_semantics'] = {'queue_representation': {
        'zendesk': 'native group_id', 'freshdesk': 'native group_id', 'helpscout': 'native mailbox_id',
        'reamaze': 'native category', 'gorgias': 'explicit queue tag; not native team assignment'}[app]}
    if app == 'zendesk':
        result['world'][app]['groups'] = [{'id': before, 'name': before}, {'id': after, 'name': after}]
    if app == 'helpscout':
        result['world'][app]['mailboxes'] = [
            _fill_required({'collection': [app, 'mailboxes']}, {'id': key, 'name': key})
            for key in (before, after)]
    return result
