"""Creation revision: the pinned LinkedIn UGC endpoint supports PUBLIC only."""
from .construction_assets import require
from .construction_create_effect_asset_v2 import native_create_effect as previous_create


def native_create_effect(params, context, alias):
    if params.get('application') == 'linkedin':
        require(params.get('operation_fields', {}).get('visibility') == 'PUBLIC',
                'pinned LinkedIn UGC creation supports PUBLIC only; private visibility is unavailable')
    return previous_create(params, context, alias)
