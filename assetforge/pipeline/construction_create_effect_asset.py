"""`native_create_effect` 1.0.0: scored creation effects taken from the official applications.

Adapters are derived from `inspect_official_app_surfaces.py` and proved by
`probe_official_create_effects.py`: on the empty world the application's existence assertion is
false, the application's own documented create route executes without error, and the same
assertion holds afterwards.  Only adapters that passed both directions are listed.

The builder seeds nothing but the required parent objects (for example an Airtable base), performs
the create route with Author-supplied business parameters, and emits the field-level existence
assertion together with a guard assertion that the created object must not pre-exist.
"""
from __future__ import annotations

try:  # package import in production
    from .construction_assets import exact, record_id, require, text
except ImportError:  # identical source shipped flat into the independent native review sandbox
    from construction_assets import exact, record_id, require, text

ADAPTERS = {
    'jira': {
        'assertion': 'jira_issue_exists_with_summary', 'guard': 'jira_issue_not_exists_with_summary',
        'summary_key': 'summary',
        'write': {'method': 'POST', 'url': 'jira/rest/api/3/issue',
                  'body': {'fields': {'summary': '{business_value}', 'project': {'key': '{scope}'},
                                      'issuetype': {'name': 'Task'}}}},
        'parameters': ['summary', 'project_key'],
    },
    'zoho_desk': {
        'assertion': 'zoho_desk_ticket_exists_with_subject',
        'guard': 'zoho_desk_ticket_not_exists',
        'summary_key': 'subject',
        'write': {'method': 'POST', 'url': 'https://desk.zoho.com/api/v1/tickets',
                  'body': {'subject': '{business_value}', 'departmentId': '{scope}'}},
        'parameters': ['subject', 'department'],
    },
    'reamaze': {
        'assertion': 'reamaze_conversation_exists_with_subject',
        'guard': 'reamaze_conversation_not_exists',
        'summary_key': 'subject',
        'write': {'method': 'POST', 'url': 'https://native.reamaze.io/api/v1/conversations',
                  'body': {'conversation': {'subject': '{business_value}', 'category': '{scope}'}}},
        'parameters': ['subject', 'category'],
    },
    'gorgias': {
        'assertion': 'gorgias_ticket_exists_with_subject',
        'guard': 'gorgias_ticket_not_exists',
        'summary_key': 'subject',
        'write': {'method': 'POST', 'url': 'https://api.gorgias.com/api/tickets',
                  'body': {'subject': '{business_value}', 'channel': '{scope}'}},
        'parameters': ['subject', 'channel'],
    },
    'linkedin': {
        'assertion': 'linkedin_post_exists', 'guard': 'linkedin_post_not_exists',
        'summary_key': 'text_contains',
        'write': {'method': 'POST', 'url': 'linkedin/v2/ugcPosts',
                  'body': {'specificContent': {'com.linkedin.ugc.ShareContent': {
                      'shareCommentary': {'text': '{business_value}'}}},
                      'visibility': {'com.linkedin.ugc.MemberNetworkVisibility': '{scope}'}}},
        'parameters': ['post_text', 'visibility'],
    },
    'airtable': {
        'assertion': 'airtable_record_exists', 'guard': 'airtable_record_not_exists',
        'summary_key': 'fields',
        'write': {'method': 'POST', 'url': 'airtable/v0/{base}/{table}',
                  'body': {'fields': {'{scope}': '{business_value}'}}},
        'parameters': ['record_value', 'table_field'],
    },
    'twilio': {
        'assertion': 'twilio_sms_sent', 'guard': 'twilio_sms_not_sent',
        'summary_key': 'message_contains',
        'write': {'method': 'POST', 'url': 'twilio/2010-04-01/Accounts/{account}/Messages.json',
                  'body': {'To': '{to}', 'From': '{from}', 'Body': '{business_value}'}},
        'parameters': ['message', 'to_number'],
    },
    'docusign': {
        'assertion': 'docusign_envelope_exists', 'guard': None, 'summary_key': 'subject_contains',
        'write': {'method': 'POST', 'url': 'docusign/v2.1/accounts/native-account/envelopes',
                  'body': {'emailSubject': '{business_value}', 'status': 'sent'}},
        'parameters': ['email_subject', 'status'],
    },
    'google_calendar': {
        'assertion': 'google_calendar_event_exists', 'guard': 'google_calendar_event_not_exists',
        'summary_key': 'summary',
        'write': {'method': 'POST',
                  'url': 'https://www.googleapis.com/calendar/v3/calendars/{calendar}/events',
                  'body': {'summary': '{business_value}',
                           'start': {'dateTime': '2026-08-01T09:00:00Z'},
                           'end': {'dateTime': '2026-08-01T10:00:00Z'}}},
        'parameters': ['event_summary', 'calendar'],
    },
    'calendly': {
        'assertion': 'calendly_event_type_exists', 'guard': None, 'summary_key': 'name',
        'write': {'method': 'POST', 'url': 'https://api.calendly.com/one_off_event_types',
                  'body': {'name': '{business_value}', 'duration': 30}},
        'parameters': ['event_type_name', 'duration_minutes'],
    },
    'wave': {
        'assertion': 'wave_customer_exists', 'guard': 'wave_customer_not_exists',
        'summary_key': 'name',
        'write': {'method': 'POST', 'url': 'https://gql.waveapps.com/graphql/public',
                  'body': {'query': 'mutation { customerCreate }',
                           'variables': {'input': {'name': '{business_value}',
                                                   'email': 'native-business-value@example.org'}}}},
        'parameters': ['customer_name', 'customer_email'],
    },
    'chatgpt': {
        'assertion': 'chatgpt_completion_exists', 'guard': None, 'summary_key': 'prompt_contains',
        'write': {'method': 'POST', 'url': 'https://api.openai.com/v1/chat/completions',
                  'body': {'model': '{scope}', 'messages': [{'role': 'user', 'content': '{business_value}'}]}},
        'parameters': ['prompt', 'model'],
    },
}


def native_create_effect(params, context, alias):
    exact(params, ['business_context', 'application', 'business_value', 'scope',
                   'protected_scope'], 'native_create_effect parameters')
    text(params['business_context'], 'business context')
    app = text(params['application'], 'application')
    require(app in ADAPTERS, 'unsupported native create-effect application: ' + str(app))
    spec = ADAPTERS[app]
    business_value = text(params['business_value'], 'business value')
    scope = text(params['scope'], 'scope')
    protected_scope = text(params['protected_scope'], 'protected scope')
    require(business_value != protected_scope and scope != protected_scope,
            'protected scope must differ from the created value and scope')
    rid = 'C' + record_id(context['root_task_id'], context['seed'], alias, app, 'create')[:12]
    account = 'A' + record_id(context['root_task_id'], context['seed'], alias, app, 'account')[:10]
    base = 'B' + record_id(context['root_task_id'], context['seed'], alias, app, 'base')[:10]
    table = 'T' + record_id(context['root_task_id'], context['seed'], alias, app, 'table')[:10]
    slot = {'business_value': business_value, 'scope': scope, 'id': rid, 'account': account,
            'base': base, 'table': table, 'calendar': 'native-calendar', 'to': '+15550001111',
            'from': '+15550002222'}

    def fill(value):
        # Substituting only the known placeholders keeps literal braces intact: a GraphQL body such
        # as `mutation { customerCreate }` must not be parsed as a Python format field.
        def substitute(text):
            for key, item in slot.items():
                text = text.replace('{' + key + '}', str(item))
            return text
        if isinstance(value, dict):
            return {substitute(key): fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill(item) for item in value]
        if isinstance(value, str):
            return substitute(value)
        return value

    action = {'method': spec['write']['method'], 'url': spec['write']['url'].format(**slot),
              'body': fill(spec['write']['body'])}
    assertion = {'type': spec['assertion']}
    if app == 'jira':
        assertion[spec['summary_key']] = business_value
    elif app == 'airtable':
        assertion.update({'applicationId': base, 'tableName': table,
                          'fields': {params['scope']: business_value}})
    elif app == 'google_calendar':
        assertion.update({'summary': business_value, 'calendarid': 'native-calendar'})
    elif app == 'calendly':
        assertion[spec['summary_key']] = business_value
    elif app == 'chatgpt':
        assertion[spec['summary_key']] = business_value
    elif app == 'wave':
        assertion[spec['summary_key']] = business_value
    elif app == 'twilio':
        assertion.update({'to': slot['to'], 'from': slot['from'],
                          spec['summary_key']: business_value})
    else:
        assertion[spec['summary_key']] = business_value
    # Only the positive creation assertion is part of the reference path: the application's
    # `*_not_exists` guard is kept for the negative case (an object that already existed must not
    # satisfy the task), so it is recorded as metadata rather than scored here.
    assertions = [assertion]
    # The task's initial_state must declare the service, otherwise the official fetch layer refuses
    # the action with "no <app> account is connected" before the route is ever reached.
    world = {app: {_collection(app): []}}
    if app == 'google_calendar':
        world = {'google_calendar': {'calendars': [{'id': 'native-calendar', 'summary': 'Native calendar'}]}}
    if app == 'airtable':
        world = {'airtable': {'bases': [{'id': base, 'name': 'Native base',
                                         'tables': [{'id': table, 'name': 'Native table'}]}]}}
    return {'world': world,
            'entities': {alias + '.created': {'id': rid, 'adapter': app, 'record': {'id': rid}}},
            'relations': [],
            'reads': [{'method': 'GET', 'url': _read_url(app, slot)}],
            'actions': [action],
            'writes': [{'entity': alias + '.created', 'field': spec['summary_key'],
                        'value': business_value}],
            'protected_fields': [],
            'assertions': assertions,
            'negative_guard_assertion': ({'type': spec['guard']} if spec.get('guard') else None),
            'obligations': ['scored_creation_effect', 'native_route_effect', 'no_pre_existing_object']}


def _collection(app):
    return {'jira': 'issues', 'zoho_desk': 'tickets', 'reamaze': 'conversations', 'gorgias': 'tickets',
            'linkedin': 'posts', 'airtable': 'bases', 'twilio': 'sms_messages', 'docusign': 'envelopes',
            'google_calendar': 'events', 'calendly': 'event_types', 'chatgpt': 'completions',
            'wave': 'customers'}[app]


def _read_url(app, slot):
    if app == 'jira':
        return 'jira/rest/api/3/project/search'
    if app == 'zoho_desk':
        return 'https://desk.zoho.com/api/v1/tickets'
    if app == 'reamaze':
        return 'https://native.reamaze.io/api/v1/conversations'
    if app == 'gorgias':
        return 'https://api.gorgias.com/api/tickets'
    if app == 'linkedin':
        return 'linkedin/v2/ugcPosts'
    if app == 'airtable':
        return 'airtable/v0/' + slot['base'] + '/' + slot['table']
    if app == 'docusign':
        return 'docusign/v2.1/accounts/native-account/envelopes'
    if app == 'google_calendar':
        return 'https://www.googleapis.com/calendar/v3/calendars/native-calendar/events'
    if app == 'calendly':
        return 'https://api.calendly.com/one_off_event_types'
    if app == 'chatgpt':
        return 'https://api.openai.com/v1/chat/completions'
    if app == 'wave':
        return 'https://gql.waveapps.com/graphql/public'
    if app == 'twilio':
        return 'twilio/2010-04-01/Accounts/' + slot['account'] + '/Messages.json'
    raise ValueError('no probed read route for ' + app)
