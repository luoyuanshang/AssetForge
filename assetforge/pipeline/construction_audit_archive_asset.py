"""`audit_archive_state` 1.0.0 — self-authored extension: archive an audited record.

A closed audit is a business structure with two required effects: the archived copy must exist in
the archive table with the audit identity **and** the source record must stay unchanged.  Official
applications offer either the source or the archive surface, never the pair; this asset composes
them and asserts both sides.
"""
from __future__ import annotations

import copy

try:  # package import in production
    from .construction_assets import exact, record_id, require, text
    from .construction_field_state_asset import _fill_required
except ImportError:  # identical source shipped flat into the independent native review sandbox
    from construction_assets import exact, record_id, require, text
    from construction_field_state_asset import _fill_required

SOURCES = {
    'zendesk': {'collection': 'tickets', 'seed': {'subject': 'native audited record'},
                'guard': {'type': 'zendesk_ticket_exists'}},
    'freshdesk': {'collection': 'tickets', 'seed': {'subject': 'native audited record'},
                  'guard': {'type': 'freshdesk_ticket_exists'}},
    'helpscout': {'collection': 'conversations', 'seed': {'subject': 'native audited record'},
                  'guard': {'type': 'helpscout_conversation_exists'}},
}


def audit_archive_state(params, context, alias):
    exact(params, ['business_context', 'source_application', 'audit_reference', 'archived_status',
                   'base_name', 'table_name'], 'audit_archive_state parameters')
    text(params['business_context'], 'business context')
    source_app = text(params['source_application'], 'source application')
    require(source_app in SOURCES, 'unsupported audit source: ' + str(source_app))
    spec = SOURCES[source_app]
    audit_reference = text(params['audit_reference'], 'audit reference')
    archived_status = text(params['archived_status'], 'archived status')
    base_name = text(params['base_name'], 'base name')
    table_name = text(params['table_name'], 'table name')
    source_id = 'A' + record_id(context['root_task_id'], context['seed'], alias, source_app, 'source')[:12]
    base_id = 'B' + record_id(context['root_task_id'], context['seed'], alias, 'archive', 'base')[:10]
    source_record = _fill_required({'collection': [source_app, spec['collection']]},
                                   {'id': source_id, **spec['seed']})
    archive_fields = {'audit_reference': audit_reference, 'source_id': source_id,
                      'status': archived_status}
    action = {'method': 'POST', 'url': 'airtable/v0/' + base_id + '/' + table_name,
              'body': {'fields': copy.deepcopy(archive_fields)}}
    archive_assertion = {'type': 'airtable_record_exists', 'applicationId': base_id,
                         'tableName': table_name, 'fields': copy.deepcopy(archive_fields)}
    return {'world': {source_app: {spec['collection']: [source_record]},
                      'airtable': {'bases': [{'id': base_id, 'name': base_name,
                                              'tables': [{'id': table_name, 'name': table_name}]}]}},
            'entities': {
                alias + '.source': {'id': source_id, 'adapter': source_app,
                                    'collection': [source_app, spec['collection']],
                                    'record': source_record},
                alias + '.archive': {'id': base_id, 'adapter': 'airtable_record',
                                     'collection': ['airtable', 'bases'],
                                     'business_key': audit_reference,
                                     'record': {'id': base_id, 'name': base_name}}},
            'relations': [],
            'reads': [{'method': 'GET', 'url': 'airtable/v0/' + base_id + '/' + table_name}],
            'actions': [action],
            'writes': [{'entity': alias + '.archive', 'field': 'audit_reference',
                        'value': audit_reference}],
            'protected_fields': [{'entity': alias + '.source', 'field': 'subject'}],
            'assertions': [archive_assertion, dict(spec['guard'])],
            'obligations': ['archive_record_created', 'audit_identity_recorded',
                            'source_record_preserved']}
