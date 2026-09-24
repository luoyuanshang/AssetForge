"""Opt-in 1.0.1 assets reuse the frozen constructors with native parameter checks."""
import copy
import functools
import hashlib
import json
from pathlib import Path
from types import FunctionType
try:
    from . import construction_assets as legacy
except ImportError:  # Identical source in the independent native review sandbox.
    import construction_assets as legacy

# Pinned to the frozen constructor this schema-checked revision was validated against.  Re-pinned on
# 2026-09-13 when the version-aware dispatch moved the 1.0.1 entries out of the legacy fallback.
LEGACY_SHA='f7ddda4fb831da56b549e00224986b09233f9485936b0b7fbcdba2d1b8b6d486'
CONTRACT_SHA='9206bc38dc410f20435a6cd83168404c44c879362e2e97fe3889014ec37f2531'
CONTRACT_PATH=Path('assetforge/artifacts/construction_assets/native_record_contracts/the-frozen-release/schema.json')
_ORIGINAL=legacy.construct


@functools.lru_cache(maxsize=1)
def validators():
    from jsonschema import Draft202012Validator, FormatChecker
    path=legacy.ROOT/CONTRACT_PATH
    if not path.exists():path=Path(__file__).with_name('native_record_contracts.json')
    raw=path.read_bytes()
    legacy.require(hashlib.sha256(raw).hexdigest()==CONTRACT_SHA,'native record contract drift')
    legacy.require(hashlib.sha256(Path(legacy.__file__).read_bytes()).hexdigest()==LEGACY_SHA,'frozen constructor drift')
    value=json.loads(raw)
    legacy.require(value['commit']==legacy.COMMIT,'record schema runtime mismatch')
    return {name:Draft202012Validator(schema,format_checker=FormatChecker()) for name,schema in value['schemas'].items()}


def linking(params,context,alias):
    part=legacy.linking(params,context,alias)
    contracts=validators()
    for symbol,entity in part['entities'].items():
        errors=list(contracts[entity['adapter']].iter_errors(entity['record']))
        legacy.require(not errors,'native asset record invalid at '+symbol+': '+
            '; '.join(str(e.message) for e in errors[:3]))
    return part


def bounded_batch(params,context,alias,prior):
    for symbol in params.get('entity_refs',[]):
        legacy.require(symbol in prior,'unresolved finite batch entity')
        adapter=prior[symbol]['adapter']
        if adapter=='hubspot_contacts':
            legacy.require(set(params.get('updates',{}))=={'jobtitle'} and params.get('protected_fields')==['phone'],
                'HubSpot 1.0.1 has verified jobtitle writes and phone preservation only; other fields need a new validated asset')
        for value in params.get('updates',{}).values():
            legacy.require(isinstance(value,str) and bool(value.strip()),'finite batch native field values must be explicit strings')
    return legacy.bounded_batch(params,context,alias,prior)


_CHECKED=FunctionType(_ORIGINAL.__code__,dict(_ORIGINAL.__globals__,BUILDERS={
    'customer_link':linking,'readable_policy_exception':legacy.policy,'bounded_contact_batch':bounded_batch}),
    name='construct_checked_101')


def construct(blueprint,catalog):
    selections=blueprint.get('assets',[])
    if all(x.get('version')=='1.0.0' for x in selections):
        return _ORIGINAL(blueprint,catalog)
    for row in selections:
        expected='1.0.0' if row['id']=='readable_policy_exception' else '1.0.1'
        legacy.require(row['version']==expected,'mixed unvalidated constructor revisions')
    validators()
    return _CHECKED(blueprint,catalog)


def install():
    """Only a new frozen cold wave installs this, never a running Author."""
    import sys
    legacy.construct=construct
    for name in ['construction_manifest','construction_author_tools','construction_examples']:
        module=sys.modules.get('assetforge.pipeline.'+name)
        if module is not None:module.construct=construct


def full_example(context,root_id,seed,catalog):
    from . import construction_examples as examples
    original=examples.blueprint
    def revised(*args):
        bp=original(*args)
        for asset in bp['assets']:
            if asset['id']!='readable_policy_exception':asset['version']='1.0.1'
        return bp
    factory=FunctionType(examples.full_example.__code__,dict(examples.full_example.__globals__,
        blueprint=revised,construct=construct),name='revised_full_example')
    value=factory(context,root_id,seed,catalog)
    for binding in value['bindings']:
        if binding['obligation_id'].endswith('.required_effect'):
            # One concrete wrong-value case can support multiple explicit
            # obligations; do not relabel it as another independent test.
            binding['case_ids']=['wrong_policy','required_effect_omitted']
    return value
