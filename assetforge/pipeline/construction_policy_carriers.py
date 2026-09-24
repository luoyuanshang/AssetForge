"""Carrier-extended `readable_policy_exception` 1.1.0 candidate builder.

`readable_policy_exception` 1.0.0 can only publish the policy text as a Slack channel topic.  The
pinned runtime registry also exposes field-level assertions for gmail message bodies
(`gmail_message_body_contains`, which inspects messages labelled SENT), so 1.1.0 adds that carrier
without changing the policy/exception semantics or relaxing any obligation.

Only carriers with a real field-level assertion are offered; anything else fails closed at
construction.  jira descriptions and notion pages are deliberately absent: the pinned registry has
no field-level assertion for either.
"""
from __future__ import annotations

try:  # package import in production
    from .construction_assets import (
        BUILDERS as _LEGACY_BUILDERS, exact, policy as _legacy_policy, record_id, require, text,
    )
except ImportError:  # identical source shipped flat into the independent native review sandbox
    from construction_assets import (
        BUILDERS as _LEGACY_BUILDERS, exact, policy as _legacy_policy, record_id, require, text,
    )

SUPPORTED_CARRIERS = ('slack_topic', 'gmail_message_body')
_SLACK_PARAMS = ('business_context', 'channel_name', 'title', 'scope', 'rule', 'exception', 'precedence', 'protected')
_GMAIL_PARAMS = ('business_context', 'sender', 'recipient', 'subject', 'title', 'scope', 'rule', 'exception',
                 'precedence', 'protected')


def _policy_text(params):
    return '\n'.join([params['title'], 'Scope: ' + params['scope'], 'Rule: ' + params['rule'],
                      'Exception (takes precedence): ' + params['exception']])


def policy_with_carriers(params, context, alias):
    """`readable_policy_exception` 1.1.0: pick the carrier explicitly, then build it natively."""
    carrier = params.get('readable_carrier')
    require(carrier in SUPPORTED_CARRIERS,
            'readable_carrier must be one of ' + ', '.join(SUPPORTED_CARRIERS)
            + ' (jira_description/notion_page have no field-level assertion in the pinned runtime)')
    for key in ('business_context', 'title', 'scope', 'rule', 'exception', 'precedence'):
        text(params[key], key)
    require(params['protected'] is True, 'read-only policy asset requires explicit policy preservation')
    require(params['precedence'] == 'exception_over_rule', 'unsupported rule precedence')
    require(params['rule'] != params['exception'], 'exception must differ from base rule')
    if carrier == 'slack_topic':
        exact(params, list(_SLACK_PARAMS) + ['readable_carrier'], 'policy parameters')
        return _legacy_policy({k: params[k] for k in _SLACK_PARAMS}, context, alias)
    exact(params, list(_GMAIL_PARAMS) + ['readable_carrier'], 'gmail policy carrier parameters')
    for key in ('sender', 'recipient', 'subject'):
        text(params[key], key)
    require('@' in params['sender'] and '@' in params['recipient'], 'gmail carrier requires real addresses')
    content = _policy_text(params)
    mid = 'M' + record_id(context['root_task_id'], context['seed'], alias, 'policy', 'gmail')[:10]
    row = {'id': mid, 'thread_id': mid, 'from_': params['sender'], 'to': [params['recipient']],
           'cc': [], 'bcc': [], 'subject': params['subject'], 'body_plain': content,
           'label_ids': ['SENT', 'INBOX'], 'attachment_ids': [], 'is_read': True, 'is_starred': False,
           'has_attachments': False, 'date': 0, 'internal_date': 0, 'size_estimate': len(content)}
    return {'world': {'gmail': {'messages': [row]}},
            'entities': {alias + '.policy': {'id': mid, 'adapter': 'gmail_message',
                                             'collection': ['gmail', 'messages'], 'record': row}},
            'relations': [],
            'reads': [{'method': 'GET', 'url': 'gmail/v1/users/me/messages'}],
            'writes': [],
            'protected_fields': [{'entity': alias + '.policy', 'field': 'body_plain'}],
            'assertions': [{'type': 'gmail_message_body_contains', 'to': params['recipient'],
                            'body_contains': content}],
            'actions': [],
            'obligations': ['readable_policy', 'exception_changes_result', 'policy_preservation',
                            'legal_alternative']}


BUILDERS = {**_LEGACY_BUILDERS, 'readable_policy_exception_carrier_extended': policy_with_carriers}
