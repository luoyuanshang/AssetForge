"""`sheet_row_state` 1.0.0 candidate: make Google Sheets a first-class construction asset.

Design doc §16.2 orders the asset library by official scored-application share, and Google Sheets is
the second most scored application in pinned the frozen release (≈30% of the reference tasks).  Until now no
admitted asset could write Sheets state, so any task whose scored obligation lived in Sheets could
not be produced by the asset pipeline at all.

The builder creates one spreadsheet, one worksheet and one explicitly identified row, writes the
Author's cells, and emits field-level assertions (`google_sheets_row_cell_equals`, falling back to
`google_sheets_cell_equals`) for every written or protected cell.  Anything the pinned registry
cannot score fails closed at construction.
"""
from __future__ import annotations

import copy

try:  # package import in production
    from .construction_assets import exact, record_id, require, text
except ImportError:  # identical source shipped flat into the independent native review sandbox
    from construction_assets import exact, record_id, require, text

SCORED_ASSERTIONS = ('google_sheets_row_cell_equals', 'google_sheets_cell_equals')

# Written cells are seeded with this explicit placeholder so that every scored cell assertion is a
# required effect of the agent's own write.  Seeding the target value instead would make the
# assertion hold in the initial state, i.e. the task would be scored without any action.
UNSET_PLACEHOLDER = 'unset'


def _assertion_type(registry_probe=None):
    """Pick the strongest available Sheets cell assertion for this pinned release."""
    try:
        from .native_runtime_interface import assertion_handlers
        handlers = assertion_handlers()
    except Exception:  # pragma: no cover - the runtime is present in production
        handlers = {}
    for name in SCORED_ASSERTIONS:
        if name in handlers:
            return name
    raise ValueError('no field-level Google Sheets cell assertion in this release')


def sheet_row_state(params, context, alias):
    exact(params, ['business_context', 'spreadsheet_title', 'worksheet_title', 'headers', 'row_key',
                   'cells', 'protected_fields', 'protected_values'], 'sheet_row_state parameters')
    text(params['business_context'], 'business context')
    text(params['spreadsheet_title'], 'spreadsheet title')
    text(params['worksheet_title'], 'worksheet title')
    headers = params['headers']
    require(isinstance(headers, list) and 2 <= len(headers) <= 60, 'explicit worksheet headers required')
    require(len(set(headers)) == len(headers), 'duplicate worksheet header')
    cells = params['cells']
    require(isinstance(cells, dict) and cells, 'explicit cell writes required')
    require(set(cells) <= set(headers), 'every written cell must be a declared header')
    protected = params['protected_fields']
    require(isinstance(protected, list) and protected, 'explicit protected cells required')
    require(set(protected) <= set(headers), 'protected cells must be declared headers')
    protected_values = params['protected_values']
    require(isinstance(protected_values, dict) and set(protected_values) == set(protected),
            'every protected cell needs an asset-seeded value and nothing else')
    require(not (set(cells) & set(protected)), 'write/protection conflict on the same cell')
    row_key = text(params['row_key'], 'row key')
    for key, value in cells.items():
        require(value != UNSET_PLACEHOLDER,
                'written cell ' + str(key) + ' may not equal the seeded placeholder')
    assertion = _assertion_type()
    sid = 'S' + record_id(context['root_task_id'], context['seed'], alias, 'sheet', 'spreadsheet')[:10]
    wid = 'W' + record_id(context['root_task_id'], context['seed'], alias, 'sheet', 'worksheet')[:10]
    rid = 'R' + record_id(context['root_task_id'], context['seed'], alias, 'sheet', 'row')[:10]
    # Only the protected cells keep their real seeded value; written cells start at the placeholder
    # (the native rows update merges cells, so the positive path cannot rely on a full overwrite).
    row_cells = {key: copy.deepcopy(protected_values[key]) for key in protected}
    row_cells.update({key: UNSET_PLACEHOLDER for key in cells})
    row_cells['row_key'] = row_key
    require('row_key' in headers, 'row_key must be a declared worksheet header')
    spreadsheet = {'id': sid, 'title': params['spreadsheet_title'], 'headers': copy.deepcopy(headers)}
    worksheet = {'id': wid, 'spreadsheet_id': sid, 'title': params['worksheet_title'],
                 'headers': copy.deepcopy(headers), 'overwrite': False}
    row = {'id': rid, 'spreadsheet_id': sid, 'worksheet_id': wid, 'row_id': row_key,
           'cells': row_cells}
    # Bind the scored row's *original worksheet identity*, not only its title: deleting the
    # worksheet and re-adding a same-titled sheet must fail, so the parent existence assertion comes
    # first (native `google_sheets_worksheet_exists` with the physical worksheet id).
    assertions = [{'type': 'google_sheets_worksheet_exists', 'spreadsheet_id': sid, 'worksheet_id': wid}]
    for key, value in cells.items():
        assertions.append({'type': assertion, 'spreadsheet_id': sid, 'worksheet_id': wid,
                           'row_id': row_key, 'column': key, 'value': value})
    for key in protected:
        value = protected_values[key]
        assertions.append({'type': assertion, 'spreadsheet_id': sid, 'worksheet_id': wid,
                           'row_id': row_key, 'column': key, 'value': value})
    return {'world': {'google_sheets': {'spreadsheets': [spreadsheet], 'worksheets': [worksheet],
                                        'rows': [row]}},
            'entities': {alias + '.row': {'id': rid, 'adapter': 'google_sheets_row',
                                          'collection': ['google_sheets', 'rows'],
                                          'business_key': row_key, 'record': row}},
            'relations': [],
            # Native the frozen release routes: values.get reads the worksheet, values_rows_update addresses the
            # row by its stable worksheet id + row id (the row endpoint matches row.worksheet_id).
            'reads': [{'method': 'GET', 'url': 'sheets/v4/spreadsheets/' + sid + '/values/' + wid}],
            'actions': [{'method': 'PUT',
                         'url': 'sheets/v4/spreadsheets/' + sid + '/values/' + wid + '/rows/' + row_key,
                         'body': {'cells': copy.deepcopy(cells)}}],
            'writes': [{'entity': alias + '.row', 'field': key, 'value': value}
                       for key, value in cells.items()],
            'protected_fields': [{'entity': alias + '.row', 'field': key} for key in protected],
            'assertions': assertions,
            'obligations': ['scored_row_state', 'protected_sibling_state', 'stable_row_identity']}
