"""Executable, external construction bindings for compile/recover/review/release."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
from .construction_assets import ROOT, canonical, construct, digest, immutable_write, load_catalog, require

SCHEMA = 'automation-construction-manifest-v1'
ROLE_SCHEMA = 'automation-construction-manifest-v3-roles'
APPLICATION_ROLE_SCHEMA = 'automation-construction-manifest-v4-application-roles'


def native_identity(row, path):
    if 'id' in row:
        return 'id', row['id']
    key = {'invoices': 'invoice_id', 'contacts': 'contact_id',
           'customers': 'customer_id'}.get(path.rsplit('.', 1)[-1])
    require(key is not None and key in row, 'asset collection lacks stable native identity at ' + path)
    return key, row[key]


def _protected_field_map(construction):
    """(app, collection, record_id) -> entity name, plus entity -> protected fields.

    The asset contract already declares which seeded fields are protected
    (`protected_fields`) and which are asserted/scored.  Everything else the asset
    seeds is ordinary starting context: an author may legitimately rewrite it.
    Enforcing the whole fragment verbatim was stricter than the contract and
    blocked otherwise valid candidates (measured 2026-09-15: editing the seeded
    gmail authority body_plain, which is neither protected nor asserted).
    """
    index = {}
    for name, entity in (construction.get('entities') or {}).items():
        collection = entity.get('collection')
        record = entity.get('record') or {}
        if isinstance(collection, list) and len(collection) == 2 and record.get('id') is not None:
            index[(collection[0], collection[1], str(record['id']))] = name
    protected = {}
    for row in (construction.get('protected_fields') or []):
        protected.setdefault(row.get('entity'), set()).add(row.get('field'))
    return index, protected


def fragment_present(fragment, state, path='initial_state', *,
                     protected=None, entity_index=None, app=None, collection=None,
                     allowed_edits=None):
    if isinstance(fragment, dict):
        require(isinstance(state, dict), 'asset state type mismatch: ' + path)
        for key, value in fragment.items():
            require(key in state, 'asset state omitted: ' + path + '.' + key)
            fragment_present(value, state[key], path + '.' + key,
                             protected=protected, entity_index=entity_index,
                             app=key if app is None else app,
                             collection=key if app is not None and collection is None else collection,
                             allowed_edits=allowed_edits)
    elif isinstance(fragment, list):
        require(isinstance(state, list), 'asset collection type mismatch: ' + path)
        # Scalar arrays (gmail `to`/`cc`/`label_ids`, worksheet `headers`, …) are asset-owned values,
        # not identified record collections.  Treating them as collections made every gmail/sheeting
        # fragment fail composition with 'asset collection lacks stable identity', which blocked the
        # whole compile/recover/review/collection chain for those carriers.
        if not fragment or all(not isinstance(row, dict) for row in fragment):
            require(fragment == state, 'asset field changed: ' + path)
            return
        for row in fragment:
            require(isinstance(row, dict), 'asset collection lacks stable identity')
            key, identity = native_identity(row, path)
            matches = [candidate for candidate in state if isinstance(candidate, dict) and candidate.get(key) == identity]
            require(len(matches) == 1, 'missing/duplicate bound identity at ' + path)
            fragment_present(row, matches[0], path + '[' + key + '=' + str(identity) + ']',
                             protected=protected, entity_index=entity_index,
                             app=app, collection=collection, allowed_edits=allowed_edits)
    else:
        if fragment == state:
            return
        # A scalar the asset seeded may be rewritten unless the contract protects
        # it.  Protection is declared per (entity, field); the entity is identified
        # by the record id at this path.
        if protected and entity_index is not None:
            field = path.rpartition('.')[2].split('[')[0]
            record_id = None
            if '[' in path and path.endswith(']'):
                record_id = path[path.rindex('[') + 1:-1].split('=')[-1]
            entity_name = entity_index.get((app, collection, str(record_id))) if record_id else None
            if entity_name is not None and field in (protected.get(entity_name) or set()):
                raise ValueError('asset field changed (protected): ' + path)
            if allowed_edits is not None:
                allowed_edits.append(path)
            return
        raise ValueError('asset field changed: ' + path)


def validate_composition(construction, source, bindings):
    """Check whole task bindings, not just local asset success."""
    # `source` is provider-authored.  Validate its shape before indexing it so a
    # malformed submission receives a readable requirement instead of a raw
    # AttributeError/TypeError that the Author cannot act on.
    require(isinstance(source, dict), 'task_source must be an object')
    require(isinstance(source.get('initial_state'), dict), 'task_source.initial_state must be an object')
    require(isinstance(source.get('assertions'), list), 'task_source.assertions must be an array')
    if construction.get('actions'):
        require(isinstance(source.get('reference_actions'), list), 'task_source.reference_actions must be an array')
    fragment_present(construction['world'], source['initial_state'])
    assertions = source['assertions']; cases = source.get('native_construction_cases') or []
    require(isinstance(bindings, list), 'explicit construction obligations required')
    required = {o['id'] for o in construction['obligations']}
    obligations = {o['id']: o for o in construction['obligations']}
    submitted = {b['obligation_id'] for b in bindings if isinstance(b, dict) and isinstance(b.get('obligation_id'), str)}
    if len(bindings) != len(required) or submitted != required:
        raise ValueError(
            'construction obligation omitted, duplicated or invented: missing='
            + json.dumps(sorted(required - submitted))
            + ' unexpected=' + json.dumps(sorted(submitted - required))
            + ' submitted_rows=' + json.dumps(len(bindings))
            + ' required_rows=' + json.dumps(len(required)))
    for assertion in construction['assertions']:
        if assertion not in assertions:
            raise ValueError('asset native assertion recipe missing from task_source.assertions: '
                             + json.dumps(assertion, ensure_ascii=False))
    for action in construction['actions']:
        if action not in source['reference_actions']:
            raise ValueError('asset effect recipe missing from declared correct path: '
                             + json.dumps(action, ensure_ascii=False))
    case_ids = {case['case_id']: case for case in cases}
    require(len(case_ids) == len(cases), 'duplicate native construction case identity')
    for row_index, row in enumerate(bindings):
        if set(row) != {'obligation_id', 'requirement', 'public_basis', 'assertion_indices', 'case_ids'}:
            raise ValueError(
                'construction binding shape mismatch at /construction_bindings/'
                + str(row_index) + ': expected='
                + json.dumps(['obligation_id', 'requirement', 'public_basis', 'assertion_indices', 'case_ids'])
                + ' actual=' + json.dumps(sorted(row)))
        require(isinstance(row['requirement'], str) and len(row['requirement'].strip()) >= 8,
                'business obligation requires an explicit Author statement')
        basis = row['public_basis']
        require(basis == {'public_request': True} or isinstance(basis, str) and basis in source['task_instruction'],
                'obligation public basis absent')
        indices = row['assertion_indices']
        obligation = obligations[row['obligation_id']]
        if obligation.get('kind') == 'structural_background':
            require(indices == [], 'structural background must not borrow scoring assertions')
            require(row['case_ids'] == [], 'structural background uses its dedicated native read evidence')
            require(obligation.get('reads') and obligation.get('entity_symbols'), 'background read contract missing')
            for symbol in obligation['entity_symbols']:
                require(construction['entities'][symbol].get('instance_role') == 'non_target_background',
                        'background obligation references a necessary effect')
                require(not any(w['entity'] == symbol for w in construction['writes']),
                        'background entity cannot carry a required write')
            continue
        require(isinstance(indices, list) and indices and all(type(i) is int and 0 <= i < len(assertions) for i in indices),
                'obligation native assertions unresolved')
        refs = row['case_ids']
        require(isinstance(refs, list) and refs and all(c in case_ids for c in refs), 'obligation native case unresolved')
        uncovered = [
            {'case_id': c, 'category': case_ids[c].get('category'),
             'case_covered_assertion_indices': case_ids[c].get('covered_assertion_indices')}
            for c in refs
            if not (set(indices) & set(case_ids[c].get('covered_assertion_indices') or []))]
        if uncovered:
            # Supervisor §42.3: hand back the answer we already computed.
            suggested = sorted(cid for cid, case in case_ids.items()
                               if set(indices) & set(case.get('covered_assertion_indices') or []))
            raise ValueError(
                'case does not cover the bound assertion: obligation_id='
                + json.dumps(row['obligation_id'])
                + ' binding_row_index=' + str(row_index)
                + ' obligation_assertion_indices=' + json.dumps(indices)
                + ' suggested_case_ids=' + json.dumps(suggested)
                + ' (bind at least one of these - they cover this obligation)'
                + ' offending_case_bindings=' + json.dumps(uncovered, ensure_ascii=False)
                + '; bind at least one referenced native case whose covered_assertion_indices '
                  'shares an index with obligation_assertion_indices')
        if row['obligation_id'].endswith('.legal_alternative'):
            require(any(case_ids[c]['category'] == 'equivalent_valid_path' for c in refs), 'legal alternative missing')
        if row['obligation_id'].endswith(('.wrong_customer_result', '.wrong_scope_result')):
            require(any(case_ids[c]['category'] in ('wrong_join', 'wrong_target', 'extra_member', 'missing_member', 'identity_substitution')
                        for c in refs), 'wrong business-result case missing')
        if row['obligation_id'].endswith('.exception_changes_result'):
            require(source.get('policy_fixtures'), 'policy asset requires native cross-world policy fixtures')
            require(any(case_ids[c]['category'] == 'wrong_policy_result' for c in refs), 'policy business-result negative missing')
    return {'obligation_count': len(bindings), 'asset_count': len(construction['asset_bindings']),
            'all_bindings_resolved': True, 'semantic_coverage_proved': False,
            'independent_review_required': True}


def reference(path):
    # Explicit contract (supervisor 2026-09-15 §4): a *reference* must be a
    # repository-relative artifact, because every consumer resolves it as
    # ``ROOT / path``.  A verified external copy may still be checked with
    # ``bound()``; it simply cannot be referenced.  Say that instead of leaking
    # ``ValueError: ... is not in the subpath of ...``.
    path = Path(path).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as error:
        raise ValueError(
            'reference() only accepts repository-relative artifacts; %s is outside %s. '
            'External copies may be verified with bound() but not referenced.'
            % (path, ROOT)) from error
    return {'path': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def bound(ref):
    path = (ROOT / ref['path']).resolve()
    # A binding ref may legitimately point outside the repo (tests build refs in
    # a temp dir; a verified copy can live elsewhere).  Containment was asserted
    # unconditionally until 2026-09-14, which turned every such path into
    # `ValueError: ... is not in the subpath of ...` instead of a hash check.
    try:
        path.relative_to(ROOT)
    except ValueError:
        pass
    require(hashlib.sha256(path.read_bytes()).hexdigest() == ref['sha256'], 'construction source binding drift: ' + ref['path'])
    return path


def create_manifest(*, blueprint, catalog_ref, source, task, bindings, execution_profile,
                    executed_protocol, native_regression, rubric_ref, expansion=None,
                    background_native_evidence=None, application_roles=None):
    catalog = load_catalog(bound(catalog_ref), catalog_ref['sha256'])
    from .native_asset_construction import construct_bound
    construction = construct_bound(blueprint, catalog_ref)
    check = validate_composition(construction, source, bindings)
    require(execution_profile and executed_protocol, 'complete executed profile and protocol required')
    from .release_runtime import PROTOCOL
    manifest = {'schema_version': SCHEMA, 'root_task_id': blueprint['root_task_id'],
                'blueprint': copy.deepcopy(blueprint), 'catalog': catalog_ref, 'construction': construction,
                'runtime_protocol': reference(PROTOCOL), 'rubric': rubric_ref,
                'execution_profile': copy.deepcopy(execution_profile), 'executed_tool_protocol': copy.deepcopy(executed_protocol),
                'source_sha256': digest(source), 'task_sha256': digest(task), 'bindings': copy.deepcopy(bindings),
                'native_regression_sha256': digest(native_regression), 'composition_check': check,
                'expansion': copy.deepcopy(expansion), 'semantic_accepted': False,
                'distribution_valid': False, 'released': False, 'training_ready': False,
                'validator_sources': [reference(Path(__file__)), reference(ROOT/'assetforge/benchmark_factory/construction_assets.py'),
                    reference(ROOT/'assetforge/benchmark_factory/native_asset_construction.py')]}
    if any(o.get('kind') == 'structural_background' for o in construction['obligations']):
        require(expansion is None, 'role manifest and expansion manifest need an explicit combined contract')
        manifest['schema_version'] = ROLE_SCHEMA
        manifest['background_native_evidence'] = copy.deepcopy(background_native_evidence)
        manifest['validator_sources'].append(reference(ROOT/'assetforge/benchmark_factory/construction_background_native.py'))
    if execution_profile.get('construction_application_roles'):
        from .construction_application_roles import validate_roles
        manifest['schema_version']=APPLICATION_ROLE_SCHEMA
        manifest['application_roles']=copy.deepcopy(application_roles)
        manifest['application_role_check']=validate_roles(application_roles,construction,source,execution_profile)
        manifest['validator_sources'].append(reference(ROOT/'assetforge/benchmark_factory/construction_application_roles.py'))
        if application_roles.get('non_target_records'):
            manifest['validator_sources'].append(reference(ROOT/'assetforge/benchmark_factory/task_background_records.py'))
    manifest['content_sha256'] = digest(manifest)
    return manifest


def validate_manifest(manifest, *, source, task, execution_profile, native_regression, stage):
    role_diagnostics = {}
    require(stage in ('compile', 'recover', 'review', 'release', 'collection'), 'unsupported manifest consumer')
    require(manifest.get('schema_version') in (SCHEMA, ROLE_SCHEMA, APPLICATION_ROLE_SCHEMA), 'unknown manifest version')
    require(manifest['content_sha256'] == digest({k: v for k, v in manifest.items() if k != 'content_sha256'}), 'manifest integrity mismatch')
    for ref in [manifest['runtime_protocol'], manifest['rubric'], *manifest['validator_sources']]:
        bound(ref)
    catalog = load_catalog(bound(manifest['catalog']), manifest['catalog']['sha256'])
    from .native_asset_construction import construct_bound
    require(construct_bound(manifest['blueprint'], manifest['catalog']) == manifest['construction'], 'construction replay differs')
    has_background = any(o.get('kind') == 'structural_background' for o in manifest['construction']['obligations'])
    require(not has_background or manifest['schema_version'] in (ROLE_SCHEMA,APPLICATION_ROLE_SCHEMA), 'background requires the role-aware manifest')
    if has_background:
        from .construction_background_native import validate_evidence
        validate_evidence(manifest.get('background_native_evidence'), manifest['construction'], source)
    require(manifest['root_task_id'] == task['task_id'], 'root identity changed')
    require(manifest['source_sha256'] == digest(source) and manifest['task_sha256'] == digest(task), 'source/task content mismatch')
    require(manifest['execution_profile'] == execution_profile, 'execution profile changed or weakened')
    if execution_profile.get('construction_application_roles'):
        from .construction_application_roles import validate_roles
        require(manifest['schema_version']==APPLICATION_ROLE_SCHEMA,'application roles require manifest v4')
        require(manifest.get('application_role_check')==validate_roles(manifest.get('application_roles'),
                manifest['construction'],source,execution_profile),'task application role binding differs')
        evidence=native_regression.get('result',{}).get('application_role_native_evidence')
        require(evidence and evidence.get('role_check')==manifest['application_role_check'],
                'application-role manifest lacks bound native role checks')
        require(evidence.get('operations') and evidence.get('effect_checks',{}).get('background_state_unchanged') is True,
                'native application role operations/effect checks missing')
        require(evidence['effect_checks'].get('operation_evidence_sha256')==digest(evidence['operations']) and
                set(evidence['effect_checks'].get('effect_applications',[]))==
                set(manifest['application_roles']['necessary_effect_applications']),
                'native effects do not bind the actual role operations')
        # 2026-09-15 downgrade (supervisor §8.2): these two checks validate construction
        # structures that the official corpus cannot calibrate - the official `info` carries
        # no policy_fixtures / join_witness / read probe at all, so a rejection here is a
        # project-local format opinion (757 and 733 rejections respectively) rather than an
        # official-contract violation.  They are recorded for the Reviewer and
        # for the diagnostics report; they no longer consume Author repair budget.
        causal=evidence.get('causal_services',{})
        role_diagnostics={
            'causal_services':{
                'declared_private_evidence_services':sorted(causal.get('private_evidence_source_services',[])),
                'required_evidence_applications':sorted(manifest['application_roles']['necessary_evidence_applications']),
                'minimum_private_evidence_sources':int(execution_profile.get('strict_minimum_private_evidence_sources',1)),
                'satisfied':set(manifest['application_roles']['necessary_evidence_applications'])<=
                            set(causal.get('private_evidence_source_services',[])) and
                            len(causal.get('private_evidence_source_services',[]))>=
                            int(execution_profile.get('strict_minimum_private_evidence_sources',1)),
                'disposition':'advisory_not_a_projection_into_a_rejection'},
            'readability':{
                'all_scored_evidence_services_have_read_witness':evidence.get('readability',{}).get('all_scored_evidence_services_have_read_witness'),
                'disposition':'advisory_not_a_projection_into_a_rejection'},
        }
        if manifest['application_roles'].get('non_target_records'):
            from .task_background_records import verify_evidence
            verify_evidence(evidence.get('task_background_records'),manifest['application_roles']['non_target_records'],source['initial_state'])
    require(manifest['native_regression_sha256'] == digest(native_regression), 'native evidence changed')
    from .native_runtime_interface import runtime_pin as COMMIT
    require(native_regression.get('status') == 'completed' and
            native_regression.get('runtime_contract') == 'pinned-runtime-world-api-assertion-scorer-v1' and
            native_regression.get('official_source_contract', {}).get('source_commit') == COMMIT,
            'new native regression contract missing')
    result = native_regression.get('result', {})
    require(result.get('strict_pass') is True and result.get('no_action_strict_pass') is False and
            result.get('reference_partial_credit') == 1.0, 'correct/no-action native boundaries incomplete')
    native_cases = result.get('native_construction_case_results', {}).get('cases', [])
    source_cases = source.get('native_construction_cases', [])
    require({c['case_id'] for c in native_cases} == {c['case_id'] for c in source_cases},
            'native cases not completely executed')
    require(all(c.get('observed_strict') is c.get('expected_strict') and
                (c.get('expected_strict') is True or c.get('failed_assertion_indices'))
                for c in native_cases), 'negative must fail for a business assertion')
    require(task['info']['initial_state'] == source['initial_state'] and task['info']['assertions'] == source['assertions'],
            'source/task projection mismatch')
    validate_composition(manifest['construction'], source, manifest['bindings'])
    return {'stage': stage, 'manifest_sha256': manifest['content_sha256'], 'passed': True,
            'role_evidence_diagnostics': role_diagnostics}


def save_bundle(directory, manifest, source, task, native_regression):
    directory = Path(directory)
    version = directory / manifest['content_sha256']
    for name, value in [('construction_manifest.json', manifest), ('source.json', source), ('task.json', task),
                        ('native_regression.json', native_regression)]:
        immutable_write(version / name, value)
    # The index is written last. A partial prior write cannot be consumed.
    immutable_write(version / 'complete.json', {'schema_version': 'construction-bundle-seal-v1',
                    'files': {name: reference(version / name) for name in
                              ('construction_manifest.json', 'source.json', 'task.json', 'native_regression.json')}})
    return version


def load_bundle(directory, stage):
    directory = Path(directory); seal = json.loads((directory/'complete.json').read_text())
    require(seal.get('schema_version') == 'construction-bundle-seal-v1' and
            set(seal.get('files', {})) == {'construction_manifest.json','source.json','task.json','native_regression.json'},
            'construction bundle incomplete or unknown')
    values = {name: json.loads(bound(ref).read_text()) for name, ref in seal['files'].items()}
    manifest = values['construction_manifest.json']
    check = validate_manifest(manifest, source=values['source.json'], task=values['task.json'],
                              execution_profile=manifest['execution_profile'],
                              native_regression=values['native_regression.json'], stage=stage)
    return values, check
