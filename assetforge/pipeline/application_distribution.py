"""Version-bound application membership, independent of seeded-state membership.

Assertion involvement includes protection. It never asserts causal necessity.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAMESPACE = ROOT / 'assetforge/artifacts/app_capabilities/runtime_application_namespace.json'
# See native_runtime_interface.py: the pipeline binds to a runtime identifier rather than to
# any particular third-party release.
from .native_runtime_interface import runtime_pin
COMMIT = runtime_pin()
ALIASES = {'help_scout': 'helpscout', 'facebook_page': 'facebook_pages',
           'linkedin_conversion': 'linkedin_conversions', 'facebook_conversion': 'facebook_conversions'}


def namespace():
    raw = NAMESPACE.read_bytes()
    catalog = json.loads(raw)
    apps = catalog['applications']
    # The application count is a property of the runtime namespace this repository was frozen
    # against; it is recorded in the artifact itself (``expected_application_count``) so a
    # different runtime build can ship a different surface without editing this check.
    expected = catalog.get('expected_application_count', len(apps))
    if len(apps) != expected or catalog.get('runtime_commit') != COMMIT:
        raise ValueError('application namespace does not match the pinned runtime release')
    return {'apps': tuple(sorted(apps)), 'assertions': catalog['assertion_application'],
            'source': {'path': str(NAMESPACE.relative_to(ROOT)), 'sha256': hashlib.sha256(raw).hexdigest()}}


def task_info(task):
    info = task.get('info')
    return json.loads(info) if isinstance(info, str) else (info if isinstance(info, dict) else task)


def name_application(name, known):
    if name in known['assertions']: return known['assertions'][name]
    prefixes = {**{a: a for a in known['apps']}, **ALIASES}
    for prefix in sorted(prefixes, key=len, reverse=True):
        if name == prefix or any(name.startswith(prefix + sep) for sep in ('_', '.', '/')):
            return prefixes[prefix]
    raise ValueError('unresolved application name: ' + name)


def assertion_applications(assertions, known=None):
    known = known or namespace()
    result = set()
    for assertion in assertions:
        if not isinstance(assertion, dict): raise ValueError('assertion is not an object')
        name = assertion.get('type') or assertion.get('assertion_type')
        if not isinstance(name, str) or name not in known['assertions']:
            raise ValueError('assertion not in the pinned registered namespace: ' + str(name))
        result.add(known['assertions'][name])
    return tuple(sorted(result))


def task_membership(task, known=None):
    known = known or namespace(); info = task_info(task)
    initial = tuple(sorted(a for a in info.get('initial_state', {}) if a != 'meta'))
    if set(initial) - set(known['apps']): raise ValueError('initial state contains unknown application')
    return {'initial_apps': initial, 'scorer_apps': assertion_applications(info.get('assertions', []), known)}
