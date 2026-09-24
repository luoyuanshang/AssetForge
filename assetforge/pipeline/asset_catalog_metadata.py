"""Correct capability labels from bound native evidence, without changing asset behavior.

The original definition and independent review remain immutable. Consumers use
the catalog's corrected labels only after this separate binding is verified.
"""
import json
from .application_distribution import namespace
from .construction_assets import require, digest
from .construction_manifest import bound, reference

FIELDS = ('applications', 'assertion_types', 'application_scoring_evidence',
          'scored_capable', 'weak_scoring_applications')


def derive_metadata(validation_ref):
    validation = json.loads(bound(validation_ref).read_text())
    catalog = json.loads(bound(validation['catalog']).read_text())
    known = namespace()
    require(validation.get('native_checks_passed') is True, 'capability correction needs passing native evidence')
    rows = {}
    for asset in catalog['assets']:
        key = asset['id'] + '@' + asset['version']
        definition = json.loads(bound(asset['definition']).read_text())
        apps = set(definition['applications'])
        require(apps <= set(known['apps']), 'capability outside frozen API namespace')
        evidence = {}
        samples = validation['asset_native_coverage'][key]
        require({s['adapter'] for s in samples} == set(asset['matrix_adapters']), 'missing capability adapter')
        for sample in samples:
            example = json.loads(bound(sample['example']).read_text())
            native = json.loads(bound(sample['native_results']).read_text())
            require(sample['passed'] and native['strict_pass'] and native['example_sha256'] == digest(example),
                    'capability sample does not bind passing native result')
            require(example['asset_id'] == asset['id'] and example['version'] == asset['version'],
                    'capability sample asset mismatch')
            if definition.get('asset_role', asset.get('asset_role')) == 'background_distractor':
                continue  # Companion assertions never give a background asset an effect.
            for assertion in example['construction']['assertions']:
                name = assertion['type']
                require(name in known['assertions'], 'unregistered capability assertion: ' + name)
                app = known['assertions'][name]
                if app in apps:
                    evidence.setdefault(app, set()).add(name)
        for adapter in asset['matrix_adapters']:
            require(len({s['context'] for s in samples if s['adapter'] == adapter}) >= 2,
                    'capability adapter lacks two contexts')
        rows[key] = {'applications': sorted(apps),
            'assertion_types': sorted({n for names in evidence.values() for n in names}),
            'application_scoring_evidence': {a: sorted(names)[0] for a, names in sorted(evidence.items())},
            'scored_capable': bool(evidence),
            'weak_scoring_applications': sorted(a for a, names in evidence.items() if all('_action_' in n for n in names))}
    return {'schema_version': 'native-bound-asset-capability-metadata-v1',
            'catalog': validation['catalog'], 'native_validation': validation_ref,
            'namespace': known['source'], 'assets': rows,
            'scope': 'capability metadata only; original definitions, behavior, native and review evidence unchanged'}


def verify_catalog_metadata(catalog):
    correction_ref = catalog.get('capability_metadata_correction')
    if correction_ref is None:
        return None
    correction = json.loads(bound(correction_ref).read_text())
    require(correction == derive_metadata(correction['native_validation']), 'capability correction differs from native evidence')
    original = json.loads(bound(correction['catalog']).read_text())
    originals = {(a['id'], a['version']): a for a in original['assets']}
    for asset in catalog['assets']:
        prior = originals[(asset['id'], asset['version'])]
        require(all(asset[k] == prior[k] for k in ('definition', 'description', 'implementation')),
                'metadata-only correction changed an asset interface')
        expected = correction['assets'][asset['id'] + '@' + asset['version']]
        require(all(asset.get(k) == expected[k] for k in FIELDS), 'catalog does not consume capability correction')
    return correction
