"""Opt-in application revision; the original per-app implementation stays intact."""
from .construction_assets import exact, text
from .construction_discovered_effect_asset_v2 import ADAPTERS, native_discovered_effect


def app_state(params, context, alias):
    app = text(params.get('application'), 'application')
    if app in {'salesforce', 'hubspot', 'slack', 'mailchimp', 'gmail'}:
        from .construction_record_effect_asset import record_effect
        return record_effect(params, context, alias)
    if app == 'mailbox_app':
        from .construction_background_asset import background_state
        return background_state(params, context, alias)
    if app == 'google_sheets':
        from .construction_sheet_row_asset import sheet_row_state
        return sheet_row_state({k: v for k, v in params.items() if k != 'application'}, context, alias)
    from .construction_create_effect_asset_v2 import OPERATION_FIELDS, native_create_effect
    # Support applications intentionally use their explicit note/preservation adapter below.
    if app in OPERATION_FIELDS and app not in {'zoho_desk', 'reamaze', 'gorgias'}:
        return native_create_effect(params, context, alias)
    if app in {'zoom', 'xero', 'quickbooks'}:
        from .construction_field_state_asset_v2 import native_field_state
        return native_field_state(params, context, alias)
    from .construction_append_effect_asset_v2 import ADAPTERS as append, native_append_effect
    if app in append:
        return native_append_effect(params, context, alias)
    keys = ['business_context', 'application', 'business_value']
    if params.get('application') == 'facebook_lead_ads': keys.append('operation_fields')
    exact(params, keys, 'app_state parameters')
    app = text(params['application'], 'application')
    if app in ADAPTERS:
        return native_discovered_effect(params, context, alias)
    raise ValueError('no validated native application adapter: ' + app)
