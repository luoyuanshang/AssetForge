"""Machine-readable parameter contracts for construction assets.

The validators in ``construction_*_asset*.py`` are frozen (they are catalog
dependencies), so the executable constraints lived only in code while the
Author only ever read prose ``ASSET.md``.  Measured effect: every ASSET.md had
zero occurrences of the phrases the validators actually enforce, so models could
only infer acceptance rules from a single example and then hit
``cannot preserve the complete field being updated``, ``unknown native record
fields`` or ``row_key must be a declared worksheet header``.

This module publishes the same constraints in the artifact the Author already
reads (``construct_business_assets`` describe output) and in the repair hint of
the failing call.  It never relaxes a gate; it only makes the existing gate
readable.
"""
from __future__ import annotations

import re


# Placeholders for the published per-asset parameter template.  The Author is
# asked to submit exactly the accepted key set; measured production failures
# (145 ``requires exactly`` rejections across 55 contract36 roots) were almost
# all one asset's key names reused for another asset -- most often
# ``business_value`` from the ``app_*`` shape leaking into
# ``application_record_effect`` and ``sheet_row_state``.  A concrete per-asset
# skeleton removes that guess without relaxing any validator.
_PLACEHOLDER = {
    'business_context': '<one-line business context for this asset>',
    'application': '<application id this asset describes>',
    'business_value': '<the business value this application must reach>',
    'collection': '<native collection name>',
    'records': '[{"entity": "<symbol>", "fields": {"<native field>": "<value>"}}]',
    'target_entity': '<entity symbol from records>',
    'value': '<the exact new value of the updated field>',
    'protected_fields': '["<sibling native field that must be preserved>"]',
    'scope_name': '<name of the stated scope in the public request>',
    'spreadsheet_title': '<spreadsheet title>',
    'worksheet_title': '<worksheet title>',
    'headers': '["<literal header>", "..."]',
    'row_key': '<business value identifying the scored row>',
    'cells': '{"<header>": "<written value>"}',
    'protected_values': '{"<header>": "<preserved value>"}',
}


def _parameter_template(keys):
    return {key: _PLACEHOLDER.get(key, '<value>') for key in keys}


def _parameter_keys(asset_id, version, context, alias):
    """Recover the exact accepted parameter key set from the frozen validator."""
    try:
        from .construction_assets import _version_builder
        builder = _version_builder(asset_id, version)
    except Exception:
        return None
    try:
        builder({}, context, alias)
    except ValueError as error:
        match = re.search(r'requires exactly ([A-Za-z0-9_,]+)', str(error))
        if match:
            return match.group(1).split(',')
    except Exception:
        return None
    return None


def _record_effect_rules():
    from .construction_app_asset import capability
    from .construction_record_effect_asset import ADAPTERS
    applications = {}
    for app, (collection, field) in ADAPTERS.items():
        definition = capability(app)['entities'][collection]
        applications[app] = {
            'collection': collection,
            'updated_field': field,
            'allowed_native_fields': sorted(definition['fields']),
            'required_native_fields': sorted(definition['required']),
        }
    rules = [
        {'rule_id': 'protected_excludes_updated_field',
         'statement': 'protected_fields must not contain the updated field of that application',
         'business_reason': 'the valued update stays observable, so the same field cannot also be protected'},
        {'rule_id': 'records_are_explicit',
         'statement': 'each record declares exactly {entity, fields}; include the updated field and every protected field',
         'business_reason': 'the target effect and the untouched sibling value must both exist in seeded state'},
        {'rule_id': 'native_fields_only',
         'statement': 'record fields must be a subset of allowed_native_fields for that application',
         'business_reason': 'the pinned native capability cannot persist fields it does not model'},
        {'rule_id': 'generated_identity',
         'statement': 'do not supply id; identities are generated from the root seed',
         'business_reason': 'stable native identity is required for assertions and for replay'},
        {'rule_id': 'target_effect_not_satisfied',
         'statement': 'the target record must not already hold the value',
         'business_reason': 'otherwise the scored effect would already be true in the initial state'},
    ]
    rules.append({'rule_id': 'gmail_protected_empty',
                  'statement': "for gmail, protected_fields must be []",
                  'business_reason': 'the gmail adapter only promises label membership, not arbitrary message fields'})
    rules.append({'rule_id': 'slack_protected_empty',
                  'statement': "for slack, protected_fields must be []",
                  'business_reason': 'the slack adapter only protects non-target topics'})
    rules.append({'rule_id': 'mailchimp_protected_subset_email',
                  'statement': "for mailchimp, protected_fields must be a subset of ['email']",
                  'business_reason': 'the subscriber audience is bound by the generated scope'})
    return applications, rules


def _sheet_row_rules():
    return [
        {'rule_id': 'headers_are_literal_columns',
         'statement': 'headers is the literal worksheet column list; row_key is a business VALUE, not a column name',
         'business_reason': 'the scored row is located by the declared header whose value equals row_key'},
        {'rule_id': 'written_and_protected_cells_are_headers',
         'statement': 'every key of cells and every entry of protected_fields must appear in headers',
         'business_reason': 'a cell assertion can only bind a declared column'},
        {'rule_id': 'protected_values_match_protected_fields',
         'statement': 'protected_values must be a dict whose key set equals protected_fields, each seeded from the asset',
         'business_reason': 'protected cells are preserved by the initial state, not restated in the request'},
        {'rule_id': 'written_cells_are_required_effects',
         'statement': 'cells are seeded with an explicit placeholder so each written cell is a required effect',
         'business_reason': 'a cell that already holds the answer would be scored without any action'},
    ]


def contract_for(asset_id, version, context, alias, applications=None):
    """Return the published parameter contract for one catalog asset."""
    contract = {'asset_id': asset_id, 'version': version}
    keys = _parameter_keys(asset_id, version, context, alias)
    if keys is None and asset_id.startswith('app_'):
        # Per-application assets dispatch to app_state/background_state rather
        # than a catalog builder, so the exact key set is published directly
        # from the frozen validator signatures.
        keys = ['business_context', 'application', 'business_value']
        contract['alternative_parameter_keys'] = {
            'background_state': ['business_context', 'application', 'collection']}
    if keys:
        contract['required_parameter_keys'] = keys
        contract['parameter_template'] = _parameter_template(keys)
        contract['parameter_template_note'] = (
            'Submit parameters with exactly these keys, in this asset\'s own shape. Do not '
            'reuse another asset\'s key names: application_record_effect and sheet_row_state '
            'take a single value object (value / cells), while app_* assets take '
            'business_value. Extra or renamed keys are rejected verbatim.')
    if asset_id == 'application_record_effect':
        allowed = applications if applications is not None else sorted(
            __import__('assetforge.pipeline.construction_record_effect_asset',
                       fromlist=['ADAPTERS']).ADAPTERS)
        contract['applications'] = list(allowed)
        app_rows, rules = _record_effect_rules()
        contract['native_fields_by_application'] = {
            app: app_rows[app] for app in allowed if app in app_rows}
        contract['record_shape'] = {'entity': 'unique record symbol', 'fields': 'object of native fields'}
        contract['rules'] = rules
    elif asset_id == 'sheet_row_state':
        contract['rules'] = _sheet_row_rules()
        contract['cell_semantics'] = ('cells are the written (scored) columns; protected_fields are preserved '
                                      'columns with asset-seeded protected_values')
    if 'rules' not in contract:
        contract['rules'] = []
    return contract


def _effective_parameters(params):
    """Return the parameter object the validator actually rejected.

    ``error_hint`` is handed the raw tool-call payload.  For
    ``construct_business_assets`` that payload is
    ``{"action": "instantiate", "assets": [{"id": ..., "parameters": {...}}]}``,
    so every constraint lives one level down.  The original implementation read
    the wrapper directly, which is why the shipped hints came back with
    ``application: null`` and ``submitted_protected_fields: null`` instead of
    the values that caused the failure.  Older callers passed the bare
    parameter object, so both shapes are accepted here.
    """
    if not isinstance(params, dict):
        return {}
    assets = params.get('assets')
    if isinstance(assets, list) and assets:
        candidates = [asset.get('parameters') for asset in assets
                      if isinstance(asset, dict) and isinstance(asset.get('parameters'), dict)]
        if candidates:
            # Prefer the candidate that carries the discriminating keys so a
            # multi-asset call reports the asset that actually failed.
            sentinels = {'application', 'records', 'headers', 'row_key', 'cells',
                         'protected_fields', 'protected_values', 'field', 'collection'}
            for candidate in candidates:
                if sentinels & set(candidate):
                    return candidate
            return candidates[0]
    return params


def _exact_keys_hint(text, params):
    """Turn ``requires exactly a,b,c`` into a missing/extra key diff.

    This is the single most frequent Author failure and the message alone does
    not say *which* keys the model added or forgot, so a model that already
    read the contract still burns an attempt per round.
    """
    match = re.search(r'requires exactly ([A-Za-z0-9_,]+)', text)
    if not match:
        return None
    required = match.group(1).split(',')
    submitted = list(params.keys())
    missing = [key for key in required if key not in submitted]
    unexpected = [key for key in submitted if key not in required]
    if not missing and not unexpected:
        return None
    return {'rule_id': 'exact_parameter_keys',
            'required_parameter_keys': required,
            'submitted_parameter_keys': submitted,
            'missing_parameter_keys': missing,
            'unexpected_parameter_keys': unexpected,
            'fix': ('resubmit parameters carrying exactly the required keys: add '
                    + (', '.join(missing) or 'nothing')
                    + '; remove ' + (', '.join(unexpected) or 'nothing')
                    + '. Do not nest them under another object and do not reuse another '
                      'asset\'s key names such as business_value.')}


def error_hint(message, params=None):
    """Return the actionable constraint behind a validator message.

    ``params`` is the exact payload the Author submitted, so the hint can list
    the allowed values for *that* application instead of restating the error.
    """
    text = str(message)
    params = _effective_parameters(params)
    exact = _exact_keys_hint(text, params)
    if exact is not None:
        return exact
    if 'cannot preserve the complete field being updated' in text:
        application = str(params.get('application') or '')
        try:
            from .construction_record_effect_asset import ADAPTERS
            updated = ADAPTERS.get(application, (None, None))[1]
        except Exception:
            updated = None
        return {'rule_id': 'protected_excludes_updated_field',
                'application': application or None,
                'updated_field': updated,
                'submitted_protected_fields': params.get('protected_fields'),
                'fix': ('remove the updated field from protected_fields; protect a different sibling field '
                        '(or use [] where the adapter requires an empty list)')}
    if 'supports native preservation of' in text:
        # The append/effect asset can only preserve the identity-bound field that the
        # application's native read route actually exposes.  Without this hint the
        # Author repeats the same parameters until the bounded repair budget dies
        # (measured 2026-09-15: 13 repeats on one root in the first production wave).
        application = str(params.get('application') or '')
        try:
            from .construction_append_effect_asset_v2 import _RECORD_ASSERTIONS
        except Exception:
            _RECORD_ASSERTIONS = {}
        supported = {app: {'protected_field': row[2], 'identity_key': row[1], 'assertion_type': row[0]}
                     for app, row in _RECORD_ASSERTIONS.items()}
        wanted = None
        for app, row in _RECORD_ASSERTIONS.items():
            if app == application:
                wanted = row
        return {'rule_id': 'native_preservation_field_is_fixed',
                'application': application or None,
                'submitted_protected_field': params.get('protected_field'),
                'required_protected_field': wanted[2] if wanted else None,
                'required_identity_key': wanted[1] if wanted else None,
                'supported_applications': supported,
                'fix': ('set protected_field (and protected_value) to the required field for this application, or '
                        'pick an application whose required protected field matches the field you need to keep; use '
                        'a different asset for any other preservation requirement')}
    if 'unsupported or conflicting fields' in text:
        application = str(params.get('application') or '')
        try:
            from .construction_field_state_asset import ADAPTERS as _FIELD_ADAPTERS
            spec = _FIELD_ADAPTERS.get(application, {})
        except Exception:
            spec = {}
        return {'rule_id': 'field_must_be_supported_and_differ_from_protected',
                'application': application or None,
                'supported_fields': sorted(spec.get('supported_fields') or []),
                'submitted_field': params.get('field'),
                'submitted_protected_field': params.get('protected_field'),
                'fix': ('choose field and protected_field from supported_fields, and make sure they are two different '
                        'fields (the protected one must not be the field you update)')}
    if 'initial and protected fields must be explicit' in text:
        application = str(params.get('application') or '')
        try:
            from .construction_record_effect_asset import ADAPTERS as _RECORD_ADAPTERS
            from .construction_app_asset import capability
            collection = _RECORD_ADAPTERS.get(application, (None, None))[0]
            definition = capability(application)['entities'][collection] if collection else {}
        except Exception:
            definition = {}
        updated = None
        try:
            from .construction_record_effect_asset import ADAPTERS as _RECORD_ADAPTERS
            updated = _RECORD_ADAPTERS.get(application, (None, None))[1]
        except Exception:
            pass
        protected = params.get('protected_fields')
        per_record = {}
        for entry in params.get('records') or []:
            if isinstance(entry, dict) and isinstance(entry.get('fields'), dict):
                fields = entry['fields']
                missing = [k for k in ([updated] if updated else []) + list(protected or []) if k and k not in fields]
                if missing:
                    per_record[str(entry.get('entity'))] = missing
        return {'rule_id': 'initial_and_protected_fields_are_required_in_every_record',
                'application': application or None,
                'updated_field': updated,
                'submitted_protected_fields': protected,
                'allowed_native_fields': sorted(definition.get('fields') or []),
                'missing_per_record': per_record,
                'fix': ('include the updated field and every protected field in each record\'s fields with distinct '
                        'values, choosing names from allowed_native_fields')}
    if 'unknown native record fields' in text:
        application = str(params.get('application') or '')
        try:
            from .construction_app_asset import capability
            from .construction_record_effect_asset import ADAPTERS
            collection = ADAPTERS.get(application, (None, None))[0]
            definition = capability(application)['entities'][collection] if collection else {}
        except Exception:
            definition = {}
        submitted = set()
        for record in params.get('records') or []:
            if isinstance(record, dict) and isinstance(record.get('fields'), dict):
                submitted |= set(record['fields'])
        allowed = sorted(definition.get('fields') or [])
        return {'rule_id': 'native_fields_only',
                'application': application or None,
                'allowed_native_fields': allowed,
                'unsupported_submitted_fields': sorted(submitted - set(allowed)),
                'fix': 'use only allowed_native_fields for this application'}
    if 'row_key must be a declared worksheet header' in text:
        return {'rule_id': 'headers_are_literal_columns',
                'submitted_headers': params.get('headers'),
                'submitted_row_key': params.get('row_key'),
                'fix': ('include the literal header "row_key" in headers and pass the row business value '
                        'in row_key; the row is located by that header value')}
    if 'every protected cell needs an asset-seeded value and nothing else' in text:
        return {'rule_id': 'protected_values_match_protected_fields',
                'submitted_protected_fields': params.get('protected_fields'),
                'submitted_protected_values_keys': sorted((params.get('protected_values') or {}).keys())
                if isinstance(params.get('protected_values'), dict) else None,
                'fix': 'protected_values keys must equal protected_fields exactly'}
    if 'Gmail adapter protects non-target label membership only' in text:
        return {'rule_id': 'gmail_protected_empty',
                'fix': 'for gmail, protected_fields must be []'}
    if 'per-application asset identity differs from selected adapter' in text:
        return {'rule_id': 'application_matches_asset_id',
                'fix': 'parameters.application must equal the app suffix of the selected app_* asset id'}
    return None
