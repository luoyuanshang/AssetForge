"""Replay bound asset constructors in the pinned environment, including its registry.

Provider orchestration deliberately has different dependencies. Never infer a
missing official capability from that process's imports, nor synthesize handlers.
"""
import os
import sys
from pathlib import Path

from .construction_assets import ROOT


def construct_bound(blueprint, catalog_ref):
    # The interpreter that has the native runtime installed.  Operators point this at
    # their own environment; by default we accept any interpreter that imports it.
    native_prefix = Path(os.environ.get('ASSETFORGE_RUNTIME_VENV', ROOT / '.runtime/venvs/runtime'))
    if Path(sys.prefix).resolve() == native_prefix.resolve():
        from .construction_assets import construct, load_catalog
        from .construction_manifest import bound
        # Importing the official rubric registers its dynamic assertion handlers.
        from .official_task_package import _official_imports
        _official_imports()
        return construct(blueprint, load_catalog(bound(catalog_ref), catalog_ref['sha256']))
    from .release_native_author_proxy import native_session
    response = native_session().request({'op': 'construct_assets',
        'blueprint': blueprint, 'catalog': catalog_ref})
    return response['result']
