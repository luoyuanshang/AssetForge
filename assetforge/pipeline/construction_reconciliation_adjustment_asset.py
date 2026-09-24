"""`reconciliation_adjustment` 1.0.0 — cross-application business structure (self-authored extension).

A reconciliation is not one application's effect: an adjustment must be recorded on the ledger row
**and** the source document must stay unchanged.  Official applications only offer one side each, so
this asset composes them:

  * a source document seeded through that application's own model (xero invoice, quickbooks invoice),
  * a Google Sheets ledger row whose written cells carry the adjustment and whose protected cells
    carry the prior values,
  * the sheet update route as the only write, plus field-level assertions on both the adjustment
    cells and the untouched source document.

Half the structure cannot score: writing the ledger while mutating the source breaks the source
assertion, and changing the source without writing the ledger breaks the cell assertions.
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
    'xero': {'collection': 'invoices', 'id_field': 'invoice_id',
             'assertion': 'xero_invoice_field_equals', 'assertion_id': 'invoice_id',
             'field': 'reference'},
    'quickbooks': {'collection': 'invoices', 'id_field': 'id',
                   'assertion': 'quickbooks_invoice_field_equals', 'assertion_id': 'invoice_id',
                   'field': 'doc_number'},
}


def reconciliation_adjustment(params, context, alias):
    exact(params, ['business_context', 'source_application', 'source_value',
                   'spreadsheet_title', 'worksheet_title', 'headers', 'row_key',
                   'adjustment_cells', 'ledger_protected_values'],
          'reconciliation_adjustment parameters')
    text(params['business_context'], 'business context')
    source_app = text(params['source_application'], 'source application')
    require(source_app in SOURCES, 'unsupported reconciliation source: ' + str(source_app))
    spec = SOURCES[source_app]
    source_value = text(params['source_value'], 'source value')
    headers = params['headers']
    require(isinstance(headers, list) and 2 <= len(headers) <= 60 and len(set(headers)) == len(headers),
            'explicit unique ledger headers required')
    cells = params['adjustment_cells']
    require(isinstance(cells, dict) and cells and set(cells) <= set(headers),
            'adjustment cells must be declared ledger headers')
    protected = params['ledger_protected_values']
    require(isinstance(protected, dict) and protected and set(protected) <= set(headers),
            'protected ledger cells must be declared headers')
    require(not (set(cells) & set(protected)), 'adjustment and protection must not overlap the same cell')
    row_key = params['row_key']
    require('row_key' in headers, 'the ledger must declare a row_key header')
    sheet_id = 'S' + record_id(context['root_task_id'], context['seed'], alias, 'recon', 'sheet')[:10]
    work_id = 'W' + record_id(context['root_task_id'], context['seed'], alias, 'recon', 'work')[:10]
    doc_id = 'R' + record_id(context['root_task_id'], context['seed'], alias, 'recon', 'doc')[:12]
    source_record = _fill_required({'collection': [source_app, spec['collection']]},
                                   {spec['id_field']: doc_id, spec['field']: source_value})
    ledger_cells = {key: 'unset' for key in cells}
    ledger_cells.update(copy.deepcopy(protected))
    ledger_cells['row_key'] = row_key
    spreadsheet = {'id': sheet_id, 'title': params['spreadsheet_title'],
                   'headers': copy.deepcopy(headers)}
    worksheet = {'id': work_id, 'spreadsheet_id': sheet_id, 'title': params['worksheet_title'],
                 'headers': copy.deepcopy(headers), 'overwrite': False}
    row = {'id': doc_id, 'spreadsheet_id': sheet_id, 'worksheet_id': work_id,
           'row_id': row_key, 'cells': ledger_cells}
    assertions = [{'type': 'google_sheets_worksheet_exists', 'spreadsheet_id': sheet_id,
                   'worksheet_id': work_id}]
    for key, value in cells.items():
        assertions.append({'type': 'google_sheets_row_cell_equals', 'spreadsheet_id': sheet_id,
                           'worksheet_id': work_id, 'row_id': row_key, 'column': key, 'value': value})
    for key, value in protected.items():
        assertions.append({'type': 'google_sheets_row_cell_equals', 'spreadsheet_id': sheet_id,
                           'worksheet_id': work_id, 'row_id': row_key, 'column': key, 'value': value})
    assertions.append({'type': spec['assertion'], spec['assertion_id']: doc_id,
                       'field': spec['field'], 'value': source_value})
    return {'world': {source_app: {spec['collection']: [source_record]},
                      'google_sheets': {'spreadsheets': [spreadsheet], 'worksheets': [worksheet],
                                        'rows': [row]}},
            'entities': {
                alias + '.document': {'id': doc_id, 'adapter': source_app,
                                      'collection': [source_app, spec['collection']],
                                      'record': source_record},
                alias + '.ledger': {'id': doc_id, 'adapter': 'google_sheets_row',
                                    'collection': ['google_sheets', 'rows'], 'business_key': row_key,
                                    'record': row}},
            'relations': [],
            'reads': [{'method': 'GET',
                       'url': 'sheets/v4/spreadsheets/' + sheet_id + '/values/' + work_id}],
            'actions': [{'method': 'PUT',
                         'url': 'sheets/v4/spreadsheets/' + sheet_id + '/values/' + work_id +
                                '/rows/' + row_key,
                         'body': {'cells': copy.deepcopy(cells)}}],
            'writes': [{'entity': alias + '.ledger', 'field': key, 'value': value}
                       for key, value in cells.items()],
            'protected_fields': [{'entity': alias + '.ledger', 'field': key} for key in protected] +
                                [{'entity': alias + '.document', 'field': spec['field']}],
            'assertions': assertions,
            'obligations': ['adjustment_recorded', 'source_document_preserved',
                            'ledger_row_identity']}
