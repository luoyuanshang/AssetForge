"""Native reset evidence for application coverage and scalar relationship changes.

This proves readable interventions and cross-world outcomes, not the semantic
validity of the Author's recomputed business outcome. Independent review remains
responsible for that distinction and for alternate shortcuts in the seed graph.
"""
import copy
import hashlib
import json
import re

from .single_app_policy_facts import _leaves, _literal_present

CONTRACT = 'five-app-native-reset-interventions-three-relationship-pairs-v1'
GUIDANCE = (
    'Provide 5-12 independent policy fixtures covering all five applications. '
    'Each fixture changes existing scalar fields in exactly one application; '
    'include base oracle GET probes that expose every changed scalar from reset '
    'and its replacement at the same response leaf in the alternate reset. '
    'Set join_witness to null for a non-relationship intervention. For at least '
    'three different application pairs, change exactly one relationship scalar '
    'and supply join_witness.base_target_pointer and alternate_target_pointer: '
    'existing native identity leaves of two different records in the other '
    'application, matching respectively the old and new relationship values. '
    'Also provide target_read_probe_value: a fresh same-type identity absent '
    'from that target application, used only in separate read diagnostics to '
    'avoid merging records through an accidental duplicate identity. '
    'Both target identity leaves must independently have native reset GET '
    'witnesses, without feeding their values into those probes. Recompute the '
    'legitimate outcome under the unchanged public policy; retain every other '
    'obligation and cross-test both action sequences in the opposite world. '
    'Coverage labels, wrong-target writes in an unchanged world, inaccessible '
    'state fields, and mere repeated text are insufficient.'
)


def bind_profile(normalized):
    required = [
        'exactly five causally necessary simulated applications',
        'three genuine joins and two linked',
        'each individual rule must leave ambiguity',
        'prove application necessity and join necessity with resettable counterfactual worlds',
        'alter or remove the relevant decisive fact or relationship',
        'then recompute the expected result',
        'merely acting on a wrong candidate in the unchanged world does not demonstrate',
        'every decisive eligibility fact, join key, policy value, and derived exact value',
        'at least one supported native read or search request without requiring that value as an input',
    ]
    if not all(text in normalized for text in required):
        raise ValueError('five-app dependency gate requires the complete observed Author obligation bundle')
    profile=dict(strict_opposite_policy_fixture=True, strict_minimum_policy_fixtures=5,
        strict_maximum_policy_fixtures=12, strict_five_app_native_dependencies=True,
        multi_app_dependency_contract=CONTRACT)
    if 'change exactly one existing scalar while leaving unrelated state unchanged' in normalized:
        profile['strict_single_scalar_dependency_intervention']=True
    return profile


def join_schema():
    return {'anyOf': [{'type': 'null'}, {'type': 'object',
        'properties': {'base_target_pointer': {'type': 'string'},
                       'alternate_target_pointer': {'type': 'string'},
                       'target_read_probe_value': {'type': 'string','minLength': 1}},
        'required': ['base_target_pointer', 'alternate_target_pointer', 'target_read_probe_value'],
        'additionalProperties': False}]}


def scalar(seed, pointer, parts):
    tokens=parts(pointer);value=seed
    if len(tokens)<3:
        raise ValueError('dependency pointer must identify an existing service scalar')
    for part in tokens:
        if isinstance(value,list):
            if not part.isdigit() or str(int(part))!=part or int(part)>=len(value):
                raise ValueError('dependency pointer requires a canonical existing index')
            value=value[int(part)]
        elif isinstance(value,dict) and part in value:
            value=value[part]
        else:
            raise ValueError('dependency pointer does not exist')
    if value is None or isinstance(value,(dict,list)):
        # Supervisor §42.4: the checker already walked to the witness node, so it can
        # name the scalars that ARE available instead of only saying "not a scalar".
        parent=tokens[:-1]
        node=seed
        for part in parent:
            node=node[int(part)] if isinstance(node,list) else node[part]
        if isinstance(node,dict):
            scalars=sorted(k for k,v in node.items() if isinstance(v,(str,int,float,bool)))
        elif isinstance(node,list):
            scalars=['index %d'%i for i,v in enumerate(node) if isinstance(v,(str,int,float,bool))][:12]
        else:
            scalars=[]
        raise ValueError('dependency witness requires a non-null existing scalar; at this node the '
                         'available scalars are ' + str(scalars[:12]))
    return tokens,value


def replace(seed,tokens,value):
    changed=copy.deepcopy(seed);parent=changed
    for token in tokens[:-1]:
        parent=parent[int(token)] if isinstance(parent,list) else parent[token]
    parent[int(tokens[-1]) if isinstance(parent,list) else tokens[-1]]=copy.deepcopy(value)
    return changed


def same_scalar(left,right):
    # Native numeric model fields can render JSON integers as floats. Python's
    # exact numeric equality admits 1200 -> 1200.0, without admitting booleans,
    # numeric strings, rounded large integers, or changed values.
    return (type(left) is type(right) or type(left) in (int,float) and type(right) in (int,float)) and left==right


def validate(*,initial_state,fixtures,oracle_actions,allowed_services,official,pointer_parts,canonical,
             require_single_scalar=False, required_services=None, minimum_relationship_pairs=3,
             require_all_services=True, native_reads_by_effect=False, allow_business_keys=False):
    services=set(required_services if required_services is not None else allowed_services)
    if required_services is None and (len(services)!=5 or len(allowed_services)!=5 or not 5<=len(fixtures)<=12):
        raise ValueError('five-app dependencies require exactly five services and 5-12 fixtures')
    if required_services is not None and (not services<=set(allowed_services) or
            not 1<=minimum_relationship_pairs<=10 or not minimum_relationship_pairs<=len(fixtures)<=12):
        raise ValueError('role-aware join requirements are malformed')
    prepared=[];covered=set();joins=set()
    for i,fixture in enumerate(fixtures):
        patches=fixture.get('initial_state_replacements') if isinstance(fixture,dict) else None
        if not isinstance(patches,dict) or not 1<=len(patches)<=16:
            raise ValueError('each dependency fixture needs 1-16 scalar changes in one application')
        if require_single_scalar and len(patches)!=1:
            raise ValueError('this Author contract requires exactly one changed scalar per dependency fixture')
        fields=[]
        for pointer,new in patches.items():
            tokens,old=scalar(initial_state,pointer,pointer_parts)
            if tokens[0] not in services or type(old) is not type(new) or old==new:
                raise ValueError('dependency intervention must change a same-type scalar in an allowed service')
            fields.append((pointer,tokens,old,new))
        apps={row[1][0] for row in fields}
        if len(apps)!=1:
            raise ValueError('application intervention must change exactly one application')
        app=next(iter(apps));covered.add(app)
        if 'join_witness' not in fixture:
            raise ValueError('five-app fixture must explicitly supply join_witness or null')
        join=fixture['join_witness'];targets=[];pair=None
        if join is not None:
            if len(fields)!=1 or not isinstance(join,dict) or set(join)!={'base_target_pointer','alternate_target_pointer','target_read_probe_value'}:
                raise ValueError('relationship intervention requires one scalar and two target identity pointers')
            for key,value in [('base_target_pointer',fields[0][2]),('alternate_target_pointer',fields[0][3])]:
                tokens,actual=scalar(initial_state,join[key],pointer_parts)
                identity_leaf=(tokens[-1] in {'card','file','list','board','conversation','invoice','contact','uuid','uri','key'}
                    or re.search(r'(?:^id$|_id$|Id$|ID$)',tokens[-1]) is not None)
                if allow_business_keys and tokens[-1] in {'email','email_address','from_','customer_email'}:
                    collection=initial_state
                    for part in tokens[:-2]:collection=collection[int(part)] if isinstance(collection,list) else collection[part]
                    identity_leaf=isinstance(collection,list) and sum(isinstance(r,dict) and r.get(tokens[-1])==actual for r in collection)==1
                # Supervisor §46.2 / user 2026-09-15 #4③: this condition used to
                # collapse five different causes into one sentence, so the Author
                # could not tell which one it had hit.  Name the exact cause and
                # echo the values the checker actually compared.
                if tokens[0] not in services:
                    raise ValueError(
                        f'join target must be a matching native identity in another seeded '
                        f'application; {key}={join[key]!r} points at service {tokens[0]!r}, '
                        f'which is not one of the seeded services {sorted(services)}'
                    )
                if tokens[0] == app:
                    raise ValueError(
                        f'join target must be a matching native identity in another seeded '
                        f'application; {key}={join[key]!r} resolves inside the intervened '
                        f'application {app!r} itself, but the target must live in a different '
                        f'seeded application'
                    )
                if type(actual) is not type(value):
                    raise ValueError(
                        f'join target must be a matching native identity in another seeded '
                        f'application; {key}={join[key]!r} currently holds a '
                        f'{type(actual).__name__} while the intervention supplies a '
                        f'{type(value).__name__}; keep the native identity type'
                    )
                if actual != value:
                    raise ValueError(
                        f'join target must be a matching native identity in another seeded '
                        f'application; {key}={join[key]!r} currently holds {actual!r} but the '
                        f'intervention supplies {value!r}; the two must be the same native '
                        f'identity value'
                    )
                if not identity_leaf:
                    business_leaves = sorted({'email', 'email_address', 'from_', 'customer_email'})
                    business_hint = (
                        ', or a business key that is unique inside its collection '
                        f'({business_leaves})'
                    ) if allow_business_keys else ''
                    raise ValueError(
                        f'join target must be a matching native identity in another seeded '
                        f'application; {key}={join[key]!r} ends in the leaf {tokens[-1]!r}, '
                        f'which is not an identity leaf. Use id/_id/Id/ID, or card/file/list/'
                        f'board/conversation/invoice/contact/uuid/uri/key'
                        + business_hint
                    )
                probe=join['target_read_probe_value']
                if (not isinstance(probe,str) or not probe or type(actual) is not type(probe)
                        or any(same_scalar(v,probe) for _,v in _leaves(initial_state[tokens[0]]))):
                    raise ValueError('target identity read probe must be fresh and preserve the native identity type')
                targets.append((join[key],tokens,actual,probe))
            if targets[0][1][0]!=targets[1][1][0] or targets[0][1][:-1]==targets[1][1][:-1]:
                raise ValueError('join must re-pair two distinct records in the same target application')
            pair=tuple(sorted((app,targets[0][1][0])));joins.add(pair)
        prepared.append((i,fields,targets,pair))
    if require_all_services and covered!=services:
        raise ValueError('counterfactual application coverage missing: '+','.join(sorted(services-covered)))
    if len(joins)<minimum_relationship_pairs:
        raise ValueError('counterfactual relationship coverage requires '+('three' if minimum_relationship_pairs==3 else str(minimum_relationship_pairs))+' different application pairs')

    probes=[(i,a) for i,a in enumerate(oracle_actions)
            if isinstance(a,dict) and str(a.get('method','GET')).upper()=='GET']
    if native_reads_by_effect:
        from .construction_application_roles import oracle_operation_evidence
        operations,_=oracle_operation_evidence(initial_state,oracle_actions)
        probes=[(i,a) for i,a in enumerate(oracle_actions) if not operations[i]['state_changing']]
    def read(seed,action):
        world=official['WorldState'](**copy.deepcopy(seed));world.meta.allowed_services=list(allowed_services)
        before=world.model_dump(mode='python')
        if native_reads_by_effect:before.pop('meta',None)
        packed=lambda v:canonical(v) if isinstance(v,(dict,list)) else v
        raw=official['api_fetch'](world,str(action.get('method','GET')).upper() if native_reads_by_effect else 'GET',
            action['url'],params=packed(action.get('params')),body=packed(action.get('body')))
        value=json.loads(raw)
        if isinstance(value,dict) and value.get('error') is not None:
            raise ValueError('dependency GET probe failed from reset')
        after=world.model_dump(mode='python')
        if native_reads_by_effect:after.pop('meta',None)
        if after!=before:
            raise ValueError('dependency GET probe mutated reset state')
        return dict(_leaves(value)),hashlib.sha256(raw.encode()).hexdigest()
    bases={i:read(initial_state,a) for i,a in probes};cache={}
    def witness(field):
        pointer,tokens,old,new=field
        cachekey=(pointer,canonical(new))
        if cachekey in cache:return cache[cachekey]
        changed=replace(initial_state,tokens,new);found=[]
        # Compare the native model's JSON form, including Decimal -> string,
        # rather than inventing coercions for arbitrary source values.
        native_base=official['WorldState'](**copy.deepcopy(initial_state)).model_dump(mode='json')
        native_changed=official['WorldState'](**copy.deepcopy(changed)).model_dump(mode='json')
        _,visible_old=scalar(native_base,pointer,pointer_parts)
        _,visible_new=scalar(native_changed,pointer,pointer_parts)
        for i,action in probes:
            if _literal_present(canonical(action),old) or _literal_present(canonical(action),new):continue
            original,oldsha=bases[i];alternate,newsha=read(changed,action)
            paths=[list(path) for path,value in original.items() if same_scalar(value,visible_old)
                and path in alternate and same_scalar(alternate[path],visible_new)]
            if paths:found.append(dict(oracle_index=i,response_paths=paths,
                base_response_sha256=oldsha,alternate_response_sha256=newsha))
        if not found:raise ValueError('no native reset read witness for dependency scalar '+pointer)
        cache[cachekey]=dict(pointer=pointer,native_reads=found);return cache[cachekey]
    return [dict(contract=CONTRACT if required_services is None else 'role-aware-native-counterfactual-joins-v1',
        fixture_index=i,application=fields[0][1][0],
        changed_scalars=[witness(field) for field in fields],
        relationship_pair=list(pair) if pair else None,relationship_targets=[witness(field) for field in targets],
        construction_only=True,solver_read_order_required=False,
        policy_semantic_fidelity_requires_independent_review=True,
        alternate_graph_shortcuts_require_independent_review=True)
        for i,fields,targets,pair in prepared]
