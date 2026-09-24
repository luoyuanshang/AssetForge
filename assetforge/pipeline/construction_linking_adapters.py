"""`customer_link` 1.2.0 candidate builder: more natively scoreable identity adapters.

1.0.1 offers four adapters (hubspot_contacts, salesforce_contacts, bamboohr_employees, slack_users)
and a single `exact_email_unique` semantics.  The official reference distribution uses many more
contact/user surfaces (zendesk 2.5%, freshdesk 3.2%, helpscout 2.2%, intercom 2.5%, mailchimp 1.2%,
xero 1.3%, wave 0.8%, calendly 3.2%), and all of those expose field-level assertions in pinned
the earlier version.  1.2.0 therefore adds email-keyed adapters for them.

Only apps with field-level assertions and a native email/identity key are offered; `bamboohr` is
dropped from the identity side (its only assertions are action-history), and unknown adapters fail
closed.  Non-email key types (phone/contract/ticket/case) are deferred until their native key fields
are confirmed field-by-field.
"""
from __future__ import annotations

import copy

try:  # package import in production
    from .construction_assets import (ADAPTERS as _LEGACY_ADAPTERS, exact, merge, nested, record_id,
                                      require, text, digest)
except ImportError:  # identical source shipped flat into the independent native review sandbox
    from construction_assets import (ADAPTERS as _LEGACY_ADAPTERS, exact, merge, nested, record_id,
                                     require, text, digest)

EXTENDED_ADAPTERS = {
    **_LEGACY_ADAPTERS,
    # Every extended adapter declares an adapter-owned id field, an adapter-owned business-key field
    # and a *routable* read action.  Bare service paths only resolve for the handful of services in
    # the official bare-path router table, so services routed by host use their real documented URL.
    'zendesk_users': {'path': ['zendesk', 'users'], 'key': 'email', 'id_field': 'id',
                      'key_field': 'email', 'app': 'zendesk',
                      'read': {'method': 'GET', 'url': 'https://acme.zendesk.com/api/v2/users'}},
    'freshdesk_contacts': {'path': ['freshdesk', 'contacts'], 'key': 'email', 'id_field': 'id',
                           'key_field': 'email', 'app': 'freshdesk',
                           'read': {'method': 'GET', 'url': 'https://acme.freshdesk.com/api/v2/contacts'}},
    'helpscout_customers': {'path': ['helpscout', 'customers'], 'key': 'email', 'id_field': 'id',
                            'key_field': 'email', 'app': 'helpscout',
                            'read': {'method': 'GET', 'url': 'https://api.helpscout.net/v2/customers'}},
    'intercom_contacts': {'path': ['intercom', 'contacts'], 'key': 'email', 'id_field': 'id',
                          'key_field': 'email', 'app': 'intercom',
                          'read': {'method': 'GET', 'url': 'https://api.intercom.io/contacts'}},
    'mailchimp_subscribers': {'path': ['mailchimp', 'subscribers'], 'key': 'email', 'id_field': 'id',
                              'key_field': 'email', 'app': 'mailchimp', 'needs_audience': True,
                              'read': {'method': 'GET',
                                       'url': 'https://us1.api.mailchimp.com/3.0/lists/{audience}/members'}},
    'xero_contacts': {'path': ['xero', 'contacts'], 'key': 'email', 'id_field': 'contact_id',
                      'key_field': 'email_address', 'app': 'xero',
                      'read': {'method': 'GET', 'url': 'https://api.xero.com/api.xro/2.0/Contacts'}},
    'gmail_messages': {'path': ['gmail', 'messages'], 'key': 'from_', 'id_field': 'id',
                       'key_field': 'from_', 'app': 'gmail', 'message_shaped': True,
                       'read': {'method': 'GET', 'url': 'gmail/v1/users/me/messages'}},
}

# Adapters that were advertised in the first 1.2.0 draft but cannot be built natively: calendly
# invitees need a real scheduled-event parent and wave exposes no GET route at all.  They stay
# un-offered until a version can build and read them end to end.
DROPPED_ADAPTERS = {'calendly_invitees': 'requires a real scheduled-event parent; invitee email is not readable without it',
                    'wave_customers': 'the pinned runtime route table exposes no GET read at all'}

IDENTITY_UNSAFE = ('bamboohr_employees',)

# Native models that require a display name even though identity is carried by the exact email.
NAME_REQUIRED = ('zendesk_users', 'freshdesk_contacts', 'slack_users')


def linking_extended(params, context, alias):
    exact(params, ['business_context', 'match_semantics', 'source', 'target'], 'customer_link parameters')
    text(params['business_context'], 'business context')
    require(params['match_semantics'] == 'exact_email_unique',
            'exact-email semantics only; phone/contract/ticket/case keys require confirmed native key fields')
    world, entities, keys, reads = {}, {}, {}, []
    identity_fields = []
    # One deterministic audience per asset alias: mailchimp subscribers cannot exist without their
    # parent list, and the read route addresses the list id rather than a bare collection.
    audience_id = 'L' + record_id(context['root_task_id'], context['seed'], alias, 'mailchimp', 'audience')[:10]
    for role in ('source', 'target'):
        spec = params[role]
        exact(spec, ['adapter', 'records'], role)
        adapter_name = spec['adapter']
        require(adapter_name in EXTENDED_ADAPTERS, 'unsupported identity adapter: ' + str(adapter_name))
        require(adapter_name not in IDENTITY_UNSAFE,
                adapter_name + ' exposes only action-history assertions and cannot carry a scored identity obligation')
        adapter = EXTENDED_ADAPTERS[adapter_name]
        require(isinstance(spec['records'], list) and 2 <= len(spec['records']) <= 100,
                'identity records range is 2..100')
        rows, seen_entities, keymap = [], set(), {}
        for item in spec['records']:
            exact(item, ['entity', 'business_key', 'fields'], 'identity record')
            entity = text(item['entity'], 'entity')
            key = text(item['business_key'], 'business_key')
            require(entity not in seen_entities and key not in keymap, 'ambiguous identity or duplicate entity')
            require('@' in key and key == key.strip().lower(), 'exact-email semantics require canonical lowercase email')
            seen_entities.add(entity)
            fields = copy.deepcopy(item['fields'])
            require(isinstance(fields, dict), 'record fields must be explicit')
            require(not (set(fields) & {'id', adapter['key'], 'created_at', 'updated_at', 'created_date',
                                        'last_modified_date'}),
                    'Author fields collide with asset-owned identity or time')
            rid = record_id(context['root_task_id'], context['seed'], alias, role, entity)
            row = dict(fields, **{adapter.get('id_field', 'id'): rid,
                                  adapter.get('key_field', adapter['key']): key})
            if adapter.get('needs_audience'):
                row['list_id'] = audience_id
            if adapter_name in NAME_REQUIRED and not row.get('name'):
                row['name'] = key.split('@')[0]
            if adapter.get('message_shaped'):
                row.update({'thread_id': rid, 'to': [], 'cc': [], 'bcc': [], 'label_ids': ['INBOX']})
            rows.append(row)
            symbol = f'{alias}.{role}.{entity}'
            entities[symbol] = {'id': rid, 'adapter': adapter_name, 'collection': adapter['path'],
                                'business_key': key, 'record': row}
            identity_fields.append((symbol, adapter.get('id_field', 'id')))
            keymap[key] = symbol
        rows.sort(key=lambda r: digest([context['seed'], alias, role, r[adapter.get('id_field', 'id')]]))
        world = merge(world, nested(adapter['path'], rows))
        if adapter.get('needs_audience'):
            world = merge(world, {'mailchimp': {'audiences': [{'id': audience_id,
                                                              'name': 'Identity audience'}]}})
        keys[role] = keymap
        read = copy.deepcopy(adapter['read'])
        read['url'] = read['url'].replace('{audience}', audience_id)
        reads.append(read)
    require(params['source']['adapter'] != params['target']['adapter'],
            'link asset requires different native applications')
    require(keys['source'].keys() == keys['target'].keys(), 'unmatched identity unsupported in unique-pair asset')
    relations = [{'source': keys['source'][key], 'target': keys['target'][key], 'business_key': key}
                 for key in sorted(keys['source'])]
    return {'world': world, 'entities': entities, 'relations': relations, 'reads': reads, 'writes': [],
            'protected_fields': [{'entity': symbol, 'field': field} for symbol, field in identity_fields],
            'assertions': [], 'actions': [],
            'obligations': ['stable_identity', 'cross_app_join', 'lookalike_rejection', 'protected_original_identity']}
