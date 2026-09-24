"""Explicit source identity and preserved fields for cross-application extensions."""
import copy
from .construction_assets import exact, require, text
from .construction_audit_archive_asset import audit_archive_state as legacy_archive, SOURCES as ARCHIVE_SOURCES
from .construction_reconciliation_adjustment_asset import reconciliation_adjustment as legacy_reconcile, SOURCES as LEDGER_SOURCES
from .construction_app_asset import capability


def audit_archive_state(params, context, alias):
    old_keys = ['business_context', 'source_application', 'audit_reference', 'archived_status', 'base_name', 'table_name']
    exact(params, old_keys + ['source_subject', 'source_status'], 'audited archive parameters')
    app = params['source_application']
    require(app in ARCHIVE_SOURCES, 'unknown archive source')
    subject = text(params['source_subject'], 'source subject')
    status = params['source_status']
    require(type(status) in (str, int), 'explicit native source status required')
    part = legacy_archive({k: params[k] for k in old_keys}, context, alias)
    entity = part['entities'][alias + '.source']
    entity['record'].update(subject=subject, status=status)
    part['world'][app][ARCHIVE_SOURCES[app]['collection']][0].update(subject=subject, status=status)
    noun = 'conversation' if app == 'helpscout' else 'ticket'
    part['assertions'][1] = {'type': app + '_' + noun + '_exists', noun + '_id': entity['id'],
                             'subject': subject, 'status': status}
    part['protected_fields'].append({'entity': alias + '.source', 'field': 'status'})
    source_url = {'zendesk': 'https://acme.zendesk.com/api/v2/tickets/',
                  'freshdesk': 'https://acme.freshdesk.com/api/v2/tickets/',
                  'helpscout': 'https://api.helpscout.net/v2/conversations'}[app]
    if app != 'helpscout': source_url += entity['id']
    part['reads'].insert(0, {'method': 'GET', 'url': source_url})
    part['entities'][alias + '.archive'] = {'adapter': 'airtable', 'logical_reference': alias + '.archive',
        'identity_kind': 'unresolved_creation_output', 'record': {}}
    part['capability_semantics'] = {'source_preservation': ['subject', 'status'],
        'archive_is_terminal_creation': True, 'other_source_fields_preserved': 'not promised'}
    return part


def reconciliation_adjustment(params, context, alias):
    old_keys = ['business_context', 'source_application', 'source_value', 'spreadsheet_title',
                'worksheet_title', 'headers', 'row_key', 'adjustment_cells', 'ledger_protected_values']
    exact(params, [k for k in old_keys if k != 'source_value'] + ['source_fields', 'preserved_source_fields'],
          'reconciliation parameters')
    app = params['source_application']; require(app in LEDGER_SOURCES, 'unknown reconciliation source')
    spec = LEDGER_SOURCES[app]; fields = copy.deepcopy(params['source_fields'])
    preserve = params['preserved_source_fields']
    shape = capability(app)['entities'][spec['collection']]
    require(isinstance(fields, dict) and spec['field'] in fields and
            spec['id_field'] not in fields and set(fields) <= set(shape['fields']), 'explicit native source fields required')
    require(isinstance(preserve, list) and preserve and len(preserve) == len(set(preserve)) and
            set(preserve) <= set(fields), 'preserved fields must refer to the explicit source')
    require(all(fields[k] is not None and type(fields[k]) in (str, int, float, bool) for k in preserve),
            'this adapter preserves scalar native fields')
    old = {k: params[k] for k in old_keys if k != 'source_value'}; old['source_value'] = fields[spec['field']]
    part = legacy_reconcile(old, context, alias)
    entity = part['entities'][alias + '.document']; fields[spec['id_field']] = entity['id']
    entity['record'] = fields; part['world'][app][spec['collection']] = [fields]
    # The original reference is retained as an explicitly preserved field because the ledger identity uses it.
    preserve = list(dict.fromkeys([spec['field'], *preserve]))
    part['assertions'] = [a for a in part['assertions'] if a['type'] != spec['assertion']]
    part['assertions'] += [{'type': spec['assertion'], spec['assertion_id']: entity['id'],
                            'field': k, 'value': fields[k]} for k in preserve]
    part['protected_fields'] = [r for r in part['protected_fields'] if r['entity'] != alias + '.document']
    part['protected_fields'] += [{'entity': alias + '.document', 'field': k} for k in preserve]
    if app == 'xero':
        read = {'method': 'GET', 'url': 'https://api.xero.com/api.xro/2.0/Invoices/' + entity['id']}
    else:
        read = {'method': 'GET', 'url': 'https://quickbooks.api.intuit.com/v3/company/reconciliation/query',
                'params': {'query': 'select * from Invoice'}}
    part['reads'].insert(0, read)
    part['capability_semantics'] = {'source_preservation': preserve, 'unlisted_source_fields_preserved': 'not promised'}
    return part
