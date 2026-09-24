"""Explicit native creation operations; generated outputs have no invented ID."""
import copy
from datetime import datetime
from .construction_assets import exact, record_id, require, text
from .construction_create_effect_asset import native_create_effect as legacy_create

OPERATION_FIELDS = {
    'jira': ['project_key'], 'zoho_desk': ['department'], 'reamaze': ['category'],
    'gorgias': ['channel'], 'linkedin': ['visibility'],
    'airtable': ['base_name', 'table_name', 'field'],
    'twilio': ['to_number', 'from_number'], 'docusign': ['status'],
    'google_calendar': ['calendar_title', 'start', 'end'],
    'calendly': ['duration_minutes'], 'wave': ['email'], 'chatgpt': ['model'],
}


def native_create_effect(params, context, alias):
    exact(params, ['business_context', 'application', 'business_value', 'operation_fields'], 'native creation parameters')
    app = text(params['application'], 'application')
    require(app in OPERATION_FIELDS, 'unsupported creation adapter')
    fields = params['operation_fields']
    exact(fields, OPERATION_FIELDS[app], app + ' operation fields')
    for name, value in fields.items():
        if name == 'duration_minutes':
            require(type(value) is int and 1 <= value <= 1440, 'bounded duration required')
        else:
            text(value, name)
    value = text(params['business_value'], 'business value')
    scope = str(fields[OPERATION_FIELDS[app][0]])
    if app == 'airtable': scope = fields['field']
    part = legacy_create({'business_context': params['business_context'], 'application': app,
        'business_value': value, 'scope': scope, 'protected_scope': 'unused-' +
        record_id(context['root_task_id'], context['seed'], alias, 'metadata', 'scope')}, context, alias)
    action = part['actions'][0]; assertion = part['assertions'][0]
    part['reads'] = []
    if app == 'jira':
        assertion.update(project=fields['project_key'], issuetype='Task')
    elif app == 'linkedin':
        require(fields['visibility'] in ('PUBLIC', 'CONNECTIONS'), 'unsupported LinkedIn visibility')
        assertion['visibility'] = fields['visibility']
    elif app == 'airtable':
        base = part['world'][app]['bases'][0]
        base['name'] = fields['base_name']; base['tables'][0]['name'] = fields['table_name']
        part['reads'] = [{'method': 'GET', 'url': action['url']}]
    elif app == 'twilio':
        require(fields['to_number'].startswith('+') and fields['from_number'].startswith('+'), 'international phone numbers required')
        action['body'].update(To=fields['to_number'], From=fields['from_number'])
        assertion.update(to=fields['to_number'], **{'from': fields['from_number']})
        assertion.pop('message_contains', None)
        assertion['body_contains'] = value
    elif app == 'docusign':
        require(fields['status'] in ('created', 'sent'), 'supported initial envelope state required')
        action['body']['status'] = fields['status']; assertion['status'] = fields['status']
    elif app == 'google_calendar':
        start = datetime.fromisoformat(fields['start'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(fields['end'].replace('Z', '+00:00'))
        require(start.tzinfo is not None and end.tzinfo is not None and end > start, 'explicit ordered timezone-aware event times required')
        cid = 'G' + record_id(context['root_task_id'], context['seed'], alias, app, 'calendar')[:12]
        action['url'] = action['url'].replace('native-calendar', cid)
        action['body'].update(start={'dateTime': start.isoformat()}, end={'dateTime': end.isoformat()})
        part['world'][app]['calendars'] = [{'id': cid, 'summary': fields['calendar_title']}]
        assertion.update(calendarid=cid, start=start.isoformat(), end=end.isoformat())
        part['reads'] = [{'method': 'GET', 'url': action['url']}]
    elif app == 'calendly':
        action['body']['duration'] = fields['duration_minutes']
        assertion['duration_minutes'] = fields['duration_minutes']
    elif app == 'wave':
        require('@' in fields['email'], 'customer email required')
        action['body']['variables']['input']['email'] = fields['email']; assertion['email'] = fields['email']
    elif app == 'chatgpt':
        assertion['model'] = fields['model']
    part['entities'] = {alias + '.created': {'adapter': app, 'logical_reference': alias + '.created',
        'identity_kind': 'unresolved_creation_output', 'record': {}}}
    part['capability_semantics'] = {'output_identity': 'unresolved_creation_output',
        'subsequent_id_consumption_supported': False,
        'scoring_boundary': 'only the emitted native predicate fields; no exact terminal-state claim for action predicates'}
    part.pop('negative_guard_assertion', None)
    return part
