"""Asset admission is per immutable asset, following real native and agent review."""
import hashlib
import json
from .construction_assets import ROOT,require
from .construction_manifest import bound
from .asset_review_decisions import normalize_decisions,versioned_id


def check_asset_admission(asset, admission, *, catalog=None, catalog_ref=None, _memo=None):
    memo={} if _memo is None else _memo
    def checked(ref):
        path=(ROOT/ref['path']).resolve();path.relative_to(ROOT)
        key=('bytes',str(path))
        if key not in memo:
            raw=path.read_bytes();memo[key]=(hashlib.sha256(raw).hexdigest(),raw)
        observed,raw=memo[key]
        require(observed==ref['sha256'],'asset admission evidence drift: '+ref['path'])
        return raw
    def read(ref):
        key=('json',ref['path'],ref['sha256'])
        if key not in memo:memo[key]=json.loads(checked(ref))
        return memo[key]
    validation=read(admission['native_validation'])
    review=read(admission['independent_review'])
    require(validation.get('native_checks_passed') is True and len({x['context'] for x in validation['examples']})>=2,
            'two independent business contexts not validated')
    require(review.get('complete') is True and review.get('actual_provider_calls',0)>0 and review.get('completion_seal'),
            'asset has no completed independent provider review')
    seal=read(review['completion_seal']);trajectory=read(review['trajectory'])
    from .construction_assets import digest
    require(seal.get('identity',{}).get('config_sha256')==digest(review['inputs']) and
            seal.get('result',{}).get('status')=='completed' and
            seal['result'].get('asset_decisions')==review.get('decision') and
            seal['result'].get('trajectory_sha256')==digest(trajectory),
            'review completion seal does not bind current inputs, decisions and trajectory')
    require(review['inputs']['validation']==admission['native_validation'],'review is not bound to the native asset validation')
    reviewed_catalog=read(validation['catalog'])
    prior=next((x for x in reviewed_catalog['assets'] if x['id']==asset['id'] and x['version']==asset['version']),None)
    require(prior is not None and all(asset[k]==prior[k] for k in ('definition','description','implementation')),
            'asset differs from independently reviewed version')
    if reviewed_catalog.get('dependency_contract') in ('asset-import-closure-v1', 'asset-construction-closure-v2'):
        current = catalog if catalog is not None else reviewed_catalog
        if catalog_ref is not None:
            require(read(catalog_ref) == current, 'admission catalog content does not match its reference')
        reviewed_dependencies={r['path']:r['sha256'] for r in reviewed_catalog.get('dependencies',[])}
        current_dependencies={r['path']:r['sha256'] for r in current.get('dependencies',[])}
        require(current.get('dependency_contract') == reviewed_catalog.get('dependency_contract') and
                reviewed_dependencies and current_dependencies == reviewed_dependencies,
                'current construction dependency closure differs from review')
        for ref in current['dependencies']:
            checked(ref)
            if ref.get('frozen_content'):
                require(ref['frozen_content']['sha256'] == ref['sha256'], 'construction source snapshot mismatch')
                checked(ref['frozen_content'])
        require(validation.get('schema_version')=='per-adapter-native-asset-validation-v2',
                'this catalog requires per-asset per-adapter native evidence')
        checked(validation['validation_implementation'])
        checked(validation['protocol'])
        if reviewed_catalog.get('dependency_contract') == 'asset-construction-closure-v2':
            from . import asset_role_evidence
            validator=validation.get('role_evidence_validator')
            require(validator is not None, 'role-specific admission validator is not bound')
            from pathlib import Path
            require(checked(validator) == Path(asset_role_evidence.__file__).read_bytes(),
                    'role evidence validator differs from native validation contract')
        required=set(prior.get('matrix_adapters') or [])
        rows=validation.get('asset_native_coverage',{}).get(versioned_id(asset),[])
        require(required and {r['adapter'] for r in rows}==required,'native coverage misses a declared adapter')
        for adapter in required:
            samples=[r for r in rows if r['adapter']==adapter]
            require(len({r['context'] for r in samples})>=2 and all(r.get('passed') is True for r in samples),
                    'adapter does not pass two independent native contexts')
            for sample in samples:
                example=read(sample['example']);native=read(sample['native_results'])
                require(example['asset_id']==asset['id'] and example['version']==asset['version'] and
                        example['adapter']==adapter and example['context']==sample['context'],
                        'native case is not for this exact asset adapter')
                from .construction_assets import digest
                require(native.get('example_sha256')==digest(example) and native.get('strict_pass') is True,
                        'native result is not bound to its functional input')
                cases={r['case_id']:r for r in native.get('cases',[])}
                require({'correct','no_action','wrong_result'}<=set(cases),'native positive/negative boundaries missing')
                require(cases['correct']['observed_strict'] is True and cases['no_action']['observed_strict'] is False and
                        cases['wrong_result']['observed_strict'] is False and
                        cases['wrong_result'].get('successful_native_calls') and
                        all(r['observed_strict'] is r['expected_strict'] for r in cases.values()),
                        'native business counterexample did not execute successfully')
                from .asset_role_evidence import validate_role_evidence
                validate_role_evidence(example, native, validation['protocol'])
    decisions=normalize_decisions(review.get('decision'),reviewed_catalog)
    require(decisions[versioned_id(asset)]['decision']=='accept','asset independent decision is not accept')
    if admission.get('review_plan'):
        plan=read(admission['review_plan'])
        require(plan['catalog']==validation['catalog'],'parallel review plan catalog drift')
        for directory in plan['review_outputs']:
            folder=(ROOT/directory).resolve();folder.relative_to(ROOT/'assetforge/runs')
            final=folder/'final.json'
            if not final.exists():continue
            other=json.loads(final.read_text())
            if not other.get('complete'):continue
            require(other.get('actual_provider_calls',0)>0 and other.get('completion_seal'),'completed review missing provider seal')
            checked(other['completion_seal']);checked(other['trajectory'])
            other_validation=read(other['inputs']['validation'])
            require(other_validation['catalog']==plan['catalog'],'companion review catalog mismatch')
            decisions=normalize_decisions(other.get('decision'),reviewed_catalog)
            require(decisions[versioned_id(asset)]['decision']=='accept','completed independent asset reject vetoes admission')
    for example in validation['examples']:
        checked(example['example']);checked(example['native_results'])
    return True


def require_admitted_catalog(catalog,catalog_ref):
    require(catalog.get('production_admitted') is True,'candidate asset catalog cannot enter production Author')
    from .asset_catalog_metadata import verify_catalog_metadata
    verify_catalog_metadata(catalog)
    memo={}
    for asset in catalog['assets']:
        require('admission' in asset,'asset admission missing')
        check_asset_admission(asset,asset['admission'],catalog=catalog,catalog_ref=catalog_ref,_memo=memo)
    return True
