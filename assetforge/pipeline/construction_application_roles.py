"""Task-local application roles; assertion involvement is not causal necessity."""
import copy
from .construction_assets import require, digest
from .application_distribution import namespace, assertion_applications

ROLE_KEYS=('necessary_effect_applications','necessary_evidence_applications','background_applications')
CONTRACT='construction-application-roles-v1'


def derive_roles(source, profile=None, oracle_rows=None, construction=None):
    """Derive the application roles mechanically instead of asking the Author.

    Policy (POLICY.md, section 3): the role split is a fact
    about the compiled task, not a business decision the Author should hand-write, and the
    Author's old declaration was additionally self-reported proof that the controller then
    re-verified by replay (measured run3: 916 pointer failures, 176 missing background
    records, 80 evidence pointers, and 302 asset-field complaints -- all from this layer,
    while the real "applications for this cell" checks fired 0 times).

    Everything needed already exists:
      * ``initial``  = top-level seeded services        (``_seeded_simulated_application_names``)
      * ``scored``   = services the assertions cover    (``assertion_applications``)
      * write / read / untouched = one oracle replay    (``oracle_operation_evidence``)
    """

    known = namespace()
    initial = set(source['initial_state']) - {'meta'}
    scored = set(assertion_applications(source['assertions'], known))
    if oracle_rows is None:
        oracle_rows, _world = oracle_operation_evidence(
            source['initial_state'], source.get('oracle_actions') or [], source['assertions'])
    effect = {app for row in oracle_rows for app in row.get('changed_applications') or []}
    touched = {str(row.get('service')) for row in oracle_rows if row.get('service')}
    # "Necessary" must mean the application actually decides something, not merely that the
    # oracle path touched it.  Measured 2026-09-16 on the `composed()` fixture: treating every
    # touched seeded application as necessary evidence produced three necessary applications
    # (['ads_app', 'mailbox_app', 'social_app']) where the cell contract has two, because a pure
    # background source (`mailbox_app`) is read by the path without deciding the score.  The
    # mechanical rule that matches the contract is: an application is necessary when the
    # oracle changes its state (effect) or an assertion scores it (evidence); anything else
    # the path merely reads stays background.
    # The asset layer already states which entities exist only as non-target background
    # (`instance_role == 'non_target_background'`); that is the mechanical signal that
    # separates a decisive read from a mere distractor read.  Measured 2026-09-16: without
    # it, `mailbox_app` (background mailbox) and `ads_app` (the decisive campaign outcome) were
    # indistinguishable, and the derived split disagreed with the cell contract.
    asset_background = set(profile.get('background_only_applications') or []) if isinstance(profile, dict) else set()
    if isinstance(construction, dict):
        from .application_distribution import name_application
        for entity in (construction.get('entities') or {}).values():
            if entity.get('instance_role') == 'non_target_background':
                app = (entity.get('collection') or [None])[0] or name_application(
                    entity.get('adapter'), known)
                if app:
                    asset_background.add(str(app))
    evidence = ((initial & touched) - effect) - asset_background
    background = ((initial | scored) - effect - evidence) | (asset_background - effect)
    return {
        'necessary_effect_applications': sorted(effect),
        'necessary_evidence_applications': sorted(evidence),
        'background_applications': sorted(background),
    }


def role_schema():
    """Author-facing role schema.

    2026-09-16 ruling: the three role lists are derived by the controller
    (``derive_roles``) from the compiled task, and the per-record witness layer
    (``non_target_records`` / ``necessary_evidence_records``) is no longer asked of the
    Author at all -- background evidence travels through the asset layer
    (``construction_background_native.validate_evidence``).  The acceptance strings are
    still accepted when a legacy lineage supplies them, but nothing is required, so a
    task can never again be rejected for the Author's bookkeeping.
    """

    return {'type':'object','properties':{k:{'type':'array','items':{'type':'string'},
                                             'uniqueItems':True} for k in ROLE_KEYS},
            'additionalProperties':True}


def validate_roles(roles, construction, source, profile):
    if roles is None:
        # Controller-derived roles (2026-09-16 ruling): the Author no longer declares them.
        roles = derive_roles(source, profile, construction=construction)
    require(isinstance(roles,dict) and set(ROLE_KEYS)<=set(roles)<=set(ROLE_KEYS)|{'necessary_evidence_records','non_target_records'},'explicit application roles are required')
    known=namespace();sets={}
    for key in ROLE_KEYS:
        rows=roles[key]
        require(isinstance(rows,list) and all(isinstance(a,str) for a in rows) and len(rows)==len(set(rows)),
                'application role list is malformed: '+key)
        sets[key]=set(rows)
        require(sets[key]<=set(known['apps']),'application role is outside pinned API toolset')
    effect,evidence,background=(sets[k] for k in ROLE_KEYS)
    necessary=effect|evidence
    require(effect and not (necessary&background),'necessary and pure background roles overlap or no target effect')
    initial=set(source['initial_state'])-{'meta'}
    scored=set(assertion_applications(source['assertions'],known))
    require(necessary|background==initial|scored,'application roles must cover exactly initial and assertion applications')
    require(effect<=scored,'necessary effects require native assertion involvement')
    require(evidence<=initial,'necessary evidence must exist in initial world')
    if not construction:
        # Controller delivery (2026-09-16): the Author no longer instantiates or merges assets,
        # so there is no construction to check.  The role split is derived from the compiled
        # task plus the cell profile, and only the per-cell application contract is enforced.
        expected = profile.get('application_count')
        if expected is not None:
            require(len(necessary) == expected,
                    'necessary application count differs from Author requirement: got %d (%s), '
                    'required %d; permitted applications for this cell are %s'
                    % (len(necessary), sorted(necessary), expected,
                       sorted(profile.get('permitted_applications') or [])))
        expected_scored = profile.get('scorer_application_count')
        if expected_scored is not None:
            require(len(scored) == expected_scored,
                    'assertion application count differs from local target')
        return {'contract': CONTRACT, 'roles': copy.deepcopy(roles),
                'business_source_sha256': digest({k: v for k, v in source.items() if k != 'meta'}),
                'initial_applications': sorted(initial), 'scorer_applications': sorted(scored),
                'necessary_applications': sorted(necessary), 'background_applications': sorted(background),
                'asset_layer_absent': True, 'causal_necessity_confirmed': False}
    from .construction_manifest import fragment_present, _protected_field_map
    # Enforce the asset contract, not more: only declared protected fields (and the
    # asset-owned scalar arrays handled inside fragment_present) are frozen; other
    # seeded scalars may be rewritten by the author, and every such edit is counted
    # so the audit trail shows exactly what was allowed.
    _entity_index,_protected=_protected_field_map(construction)
    _allowed_edits=[]
    fragment_present(construction['world'],source['initial_state'],
                     protected=_protected,entity_index=_entity_index,allowed_edits=_allowed_edits)
    validate_roles.unprotected_seeded_field_edits=list(_allowed_edits)
    from .application_distribution import name_application
    def entity_app(e):
        return e.get('collection',[None])[0] or name_application(e['adapter'],known)
    background_entities={entity_app(e) for e in construction['entities'].values()
                         if e.get('instance_role')=='non_target_background'}
    background_records=[e for e in construction['entities'].values() if e.get('instance_role')=='non_target_background']
    from .task_background_records import validate_bindings
    task_records=validate_bindings(roles.get('non_target_records',[]),source['initial_state'])
    evidence_records=[]
    for row in roles.get('necessary_evidence_records',[]):
        require(isinstance(row,dict) and set(row)=={'source_pointer','purpose'},
                'necessary evidence record fields malformed')
        from .task_background_records import pointer
        rec=pointer(source['initial_state'],row['source_pointer'])
        require(isinstance(rec,dict) and rec,'necessary evidence pointer must address a real seeded record')
        require(isinstance(row['purpose'],str) and row['purpose'].strip(),'necessary evidence purpose missing')
        evidence_records.append(row)
    background_entities.update(r['source_pointer'].split('/')[1] for r in task_records)
    require(len(background_records)+len(task_records)>=int(profile.get('minimum_non_target_background_records',0)),
            'task lacks the required bound non-target background record')
    require(background<=background_entities,'pure background app lacks bound readable background asset')
    require(not any(entity_app(construction['entities'][w['entity']]) in background for w in construction['writes']),
            'pure background app carries an asset effect')
    expected=profile.get('application_count')
    if expected is not None:
        require(len(necessary)==expected,
                'necessary application count differs from Author requirement: got %d (%s), required %d; '
                'permitted applications for this cell are %s'
                % (len(necessary),sorted(necessary),expected,sorted(profile.get('permitted_applications') or [])))
    expected_scored=profile.get('scorer_application_count')
    if expected_scored is not None:require(len(scored)==expected_scored,'assertion application count differs from local target')
    allow=profile.get('permitted_applications')
    if allow:require(initial|scored<=set(allow),'task applications outside Author allowlist')
    for group in profile.get('application_groups_exactly_one',[]):
        require(len(set(group)&necessary)==1,'required application role group is not satisfied')
    allowance=profile.get('background_application_allowance')
    if allowance is not None:require(len(background)<=allowance,'too many pure background applications')
    business_source={k:v for k,v in source.items() if k not in
                     ('schema_version','candidate_markdown_sha256','official_source_contract')}
    return {'contract':CONTRACT,'roles':copy.deepcopy(roles),'construction_sha256':digest(construction),
            'business_source_sha256':digest(business_source),'initial_applications':sorted(initial),'scorer_applications':sorted(scored),
            'necessary_applications':sorted(necessary),'background_applications':sorted(background),
            'minimum_cross_application_joins':int(profile.get('minimum_cross_application_joins',0)),
            'minimum_independent_policy_facts':int(profile.get('minimum_independent_policy_facts',0)),
            'namespace':known['source'],'causal_necessity_confirmed':False}


def oracle_operation_evidence(initial_state, oracle_actions, assertions=()):
    """Replay actions and observe effects; POST search is not a persistent write."""
    from . import official_task_package as native
    official=native._official_imports()
    world=official['WorldState'](**native.normalize_runtime_value(copy.deepcopy(initial_state)))
    world.meta.allowed_services=native._compute_allowed_services(initial_state=initial_state,
        assertions=list(assertions),tool_names=[],service_fields=list(namespace()['apps']))
    rows=[]
    for index,action in enumerate(oracle_actions):
        service=native._oracle_action_target_service(action)
        before=world.model_dump(mode='json');before.pop('meta',None)
        receipts,_=native._execute_official_action_sequence(official=official,world=world,actions=[action],label='role_operation')
        after=world.model_dump(mode='json');after.pop('meta',None)
        changed=sorted(k for k in set(before)|set(after) if before.get(k)!=after.get(k))
        rows.append({'oracle_index':index,'service':service,'state_changing':bool(changed),
                     'changed_applications':changed,'successful_native_calls':receipts,
                     'before_sha256':digest(before),'after_sha256':digest(after)})
    return rows,world


def verify_effect_roles(role_check, initial_state, assertions, operation_rows, final_world):
    from . import official_task_package as native
    known=namespace();effects=set(role_check['roles']['necessary_effect_applications'])
    background=set(role_check['background_applications'])
    changed={a for r in operation_rows for a in r['changed_applications']}
    require(not changed&background,'pure background application mutated by the correct path')
    require(effects<=changed,'necessary effect application has no actual native state change')
    initial_world=native._official_imports()['WorldState'](**native.normalize_runtime_value(copy.deepcopy(initial_state)))
    for app in effects:
        predicates=[a for a in assertions if app in assertion_applications([a],known)]
        before=native._official_score(initial_state=initial_state,assertions=predicates,world=initial_world)
        after=native._official_score(initial_state=initial_state,assertions=predicates,world=final_world)
        require(before['strict_pass'] is False and after['strict_pass'] is True,
                'necessary effect is not a newly achieved native scored result: '+app)
    return {'effect_applications':sorted(effects),'background_state_unchanged':True,
            'operation_evidence_sha256':digest(operation_rows)}
