"""Full selected-set count and semantic-evidence gate for the current curriculum.

Metric calculation is pure. Production consumers must use load_record, which
binds the independent decision, completion seal, memo and native role evidence.
"""
from collections import Counter
import hashlib
import json
import math
import re
import statistics
from .application_distribution import ROOT,namespace,task_info,task_membership
from .quota_completion import combo_cap,user_chars

BEGIN='CURRICULUM_ELIGIBILITY_BEGIN'
END='CURRICULUM_ELIGIBILITY_END'


def canonical(v):
    return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def digest(v):
    from .turn_journal import sha256_json
    return sha256_json(v)


def bound(ref,json_value=True):
    path=ref.get('path',ref.get('relative_path'))
    if not isinstance(path,str):raise ValueError('missing evidence path')
    if ref.get('path') and ref.get('relative_path') and ref['path']!=ref['relative_path']:
        raise ValueError('conflicting evidence paths')
    p=(ROOT/path).resolve();p.relative_to(ROOT);raw=p.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('evidence hash drift: '+path)
    return json.loads(raw) if json_value else raw.decode()


def completed_review(ref,source_sha,protocol):
    r=bound(ref)
    if r.get('status')!='completed' or r.get('decision')!='accept':raise ValueError('review did not accept')
    sb=r['packet']['source_binding'];migration=sb['release_migration']
    if migration['source_sha256']!=source_sha or migration['protocol_sha256']!=protocol:
        raise ValueError('review source/protocol mismatch')
    seal=bound(r['completion_seal']);trajectory=bound(r['trajectory']);memo=bound(r['memo'],False)
    if seal.get('seal_sha256')!=digest({k:v for k,v in seal.items() if k!='seal_sha256'}):
        raise ValueError('review completion seal integrity mismatch')
    result=seal['result']
    if seal.get('result_sha256')!=digest(result) or result.get('decision')!='accept' or result.get('review_id')!=r['review_id']:
        raise ValueError('review completion result mismatch')
    if result.get('trajectory_sha256')!=digest(trajectory) or result.get('memo_sha256')!=r['memo']['sha256']:
        raise ValueError('review memo/trajectory seal mismatch')
    bound(r['packet'],False)
    if result.get('packet_sha256')!=r['packet'].get('sha256'):
        raise ValueError('review packet seal mismatch')
    if not r.get('provider_request_ids') or not r.get('tool_call_counts',{}).get('code_exec'):
        raise ValueError('review lacks actual model and native execution evidence')
    return r,memo


def claims_from_memo(memo,source_sha,contract,comparison_set_sha256):
    matches=re.findall(re.escape(BEGIN)+r'\s*(.*?)\s*'+re.escape(END),memo,re.S)
    if len(matches)!=1 or memo.count(BEGIN)!=1 or memo.count(END)!=1:
        raise ValueError('current-curriculum semantic evidence missing or ambiguous')
    if matches[0].lstrip().startswith('{'):
        # Explicit historical certificates remain readable. New independent
        # Reviewers can give natural-language Markdown, without a JSON report.
        claims=json.loads(matches[0])
    else:
        from .curriculum_markdown_claims import parse
        claims=parse(matches[0],contract['old_pool_reference']['taskset_binding'])
    if claims.get('schema_version')!='automation-curriculum-semantic-review-v1' or claims.get('source_sha256')!=source_sha:
        raise ValueError('semantic claim identity mismatch')
    if claims.get('old_pool_reference')!=contract['old_pool_reference']['taskset_binding'] or claims.get('comparison_set_sha256')!=comparison_set_sha256:
        raise ValueError('semantic comparison corpus is not the frozen selection/reference')
    names=('non_target_record','hidden_constraint','semantic_distractor','protected_scope',
           'necessary_dependencies','new_semantic_family','near_duplicate')
    for name in names:
        claim=claims.get('criteria',{}).get(name,{})
        if claim.get('status') not in ('confirmed','absent','unknown') or not isinstance(claim.get('reason'),str) or not claim['reason'].strip():
            raise ValueError('missing explicit semantic judgment: '+name)
        if claim['status']=='confirmed' and (not claim.get('evidence_pointers') or not all(isinstance(p,str) and p.startswith('/') for p in claim['evidence_pointers'])):
            raise ValueError('semantic claim lacks concrete evidence pointers: '+name)
    return claims


def load_record(item,contract,comparison_set_sha256):
    b=bound(item['binding']);source=b['source_sha256'];root=b['root_task_id']
    if item.get('root_task_id')!=root or item.get('source_sha256')!=source:raise ValueError('selected root/source mismatch')
    if b.get('protocol_sha256')!=contract['official_reference']['protocol']['sha256'] or b.get('target_commit')!=contract['official_reference']['commit']:
        raise ValueError('selected task runtime mismatch')
    original=bound(b['source_task'])
    if b['source_task']['sha256']!=source:raise ValueError('original task source hash mismatch')
    profile=bound(b['full_profile_evidence'])
    from assetforge.pipeline.qualified_qa_binding import qualify
    review,_=completed_review(b['independent_review'],source,b['protocol_sha256'])
    qualify(profile,review,source,b['protocol_sha256'])
    if profile['target_task']!=b['target_task']:raise ValueError('selected target differs from native verified task')
    from assetforge.tools.gate_automation_18k_distribution import unresolved_quality_holds
    ancestry=b.get('historical_lineage',[])
    for ref in ancestry:bound(ref)
    if unresolved_quality_holds([*ancestry,{'task_id':root},{'task_id':b['task_id']}]):raise ValueError('unresolved ancestral quality hold')
    semantic_review,memo=completed_review(item['curriculum_review'],source,b['protocol_sha256'])
    semantic=claims_from_memo(memo,source,contract,comparison_set_sha256)
    profile_gate=profile['executed_profile'];native=profile['new_native_regression']['result']
    evidence=native.get('application_role_native_evidence')
    if not profile_gate.get('construction_application_roles') or not evidence:
        raise ValueError('current native role evidence needs compatibility revalidation')
    roles=evidence['role_check']['roles'];necessary=set(roles['necessary_effect_applications'])|set(roles['necessary_evidence_applications'])
    if not profile_gate.get('strict_named_gate_causal_services') or not profile_gate.get('strict_native_evidence_readability'):
        raise ValueError('necessary role causal/read gates absent')
    if native.get('strict_pass') is not True or evidence['effect_checks'].get('background_state_unchanged') is not True:
        raise ValueError('native effect/background evidence failed')
    bundle=review['packet']['source_binding'].get('construction_manifest',{})
    if not bundle.get('seal'):raise ValueError('source-bound native construction roles require the complete bundle')
    from .construction_manifest import load_bundle
    sealref=bundle['seal'];bound(sealref)
    values,check=load_bundle((ROOT/sealref.get('path',sealref.get('relative_path'))).parent,'release')
    if check['manifest_sha256']!=bundle['validation']['manifest_sha256']:
        raise ValueError('reviewed composition differs')
    if int(profile_gate.get('minimum_non_target_background_records',0))<contract['non_target_records']['minimum_per_task']:
        raise ValueError('required native non-target record gate missing')
    fixtures=native.get('policy_fixture_results',[])
    if not fixtures or not all(f.get('passed') is True and f.get('alternate_correct',{}).get('strict_pass') is True and
        f.get('base_path_in_alternate',{}).get('strict_pass') is False and
        f.get('alternate_path_in_base',{}).get('strict_pass') is False for f in fixtures):
        raise ValueError('actual two-world native policy results missing')
    if len(necessary)==1 and (int(profile_gate.get('minimum_independent_policy_facts',0))<3 or
        sum(bool(f.get('native_independent_fact')) for f in fixtures)<3):
        raise ValueError('single necessary app lacks three proven private constraints')
    if len(necessary) in (4,5):
        pairs={tuple(sorted(f.get('native_dependency_witness',{}).get('relationship_pair') or [])) for f in fixtures}
        if int(profile_gate.get('minimum_cross_application_joins',0))<2 or len(pairs-{()})<2 or () not in pairs:
            raise ValueError('four/five necessary app actual joins and separate policy branch missing')
    # Every claimed pointer addresses actual original task material, native proof,
    # role declarations or the frozen comparison evidence exposed to the Reviewer.
    # Official stored rows encode info as JSON text; Reviewer material exposes
    # that same bound content as an object. Keep the source hash on original bytes.
    material={'task':dict(original,info=task_info(original)), 'native':native,
              'roles':roles,'review_packet':semantic_review['packet']}
    from .task_background_records import pointer
    for claim in semantic['criteria'].values():
        for p in claim.get('evidence_pointers',[]):pointer(material,p)
    from .curriculum_background_evidence import verified_applications
    verified_background = verified_applications(values['construction_manifest.json'], values['source.json'], native)
    return dict(root_task_id=root,source_sha256=source,domain=b['domain'],task=b['target_task'],
        necessary_applications=sorted(necessary),background_applications=roles['background_applications'],
        verified_background_applications=verified_background,
        semantic=semantic['criteria'],evidence_verified=True)


def audit(records,contract,old_combinations):
    failures=[];N=contract['total'];known=namespace();rows=[]
    roots=Counter(r.get('root_task_id') for r in records);sources=Counter(r.get('source_sha256') for r in records)
    if len(records)!=N:failures.append('total_count')
    if None in roots or any(n!=1 for n in roots.values()):failures.append('root_identity_unique')
    if None in sources or any(n!=1 for n in sources.values()):failures.append('source_hash_unique')
    for r in records:
        if r.get('evidence_verified') is not True:failures.append('unverified_task_evidence')
        membership=task_membership(r['task'],known)
        rows.append(dict(r,**membership,prompt_chars=user_chars(r['task']),assertion_count=len(task_info(r['task']).get('assertions',[]))))
    domain=Counter(r['domain'] for r in rows);card=Counter(str(len(r['scorer_apps'])) for r in rows)
    combos=Counter(tuple(r['scorer_apps']) for r in rows);S=Counter();I=Counter();B=Counter();semantic=Counter();unknown=Counter()
    bydomain_semantic={d:Counter() for d in contract['domain_targets']}
    for r in rows:
        S.update(r['scorer_apps']);I.update(r['initial_apps'])
        backgrounds=set(r.get('background_applications',[]))
        verified=set(r.get('verified_background_applications',[]))
        necessary=set(r.get('necessary_applications',[]))
        if backgrounds & necessary:failures.append('background_necessary_role_overlap')
        state=task_info(r['task']).get('initial_state',{})
        B.update(a for a in backgrounds & verified & set(r['initial_apps']) - necessary
                 if isinstance(state.get(a),dict) and any(bool(v) for v in state[a].values()))
        for name in ('non_target_record','hidden_constraint','semantic_distractor','protected_scope','necessary_dependencies','new_semantic_family','near_duplicate'):
            status=r.get('semantic',{}).get(name,{}).get('status','unknown')
            if status=='confirmed':
                semantic[name]+=1
                if r['domain'] in bydomain_semantic:bydomain_semantic[r['domain']][name]+=1
            if status=='unknown':unknown[name]+=1;failures.append('semantic_unknown:'+name)
            if name in ('non_target_record','hidden_constraint','protected_scope','necessary_dependencies') and status!='confirmed':failures.append('semantic:'+name)
            if name=='near_duplicate' and status!='absent':failures.append('semantic:near_duplicate')
    if set(domain)-set(contract['domain_targets']):failures.append('unknown_domain')
    for d,spec in contract['domain_targets'].items():
        group=[r for r in rows if r['domain']==d]
        if domain[d]!=spec['total']:failures.append('domain:'+d)
        counts=Counter(str(len(r['scorer_apps'])) for r in group)
        if dict(counts)!=spec['scorer_app_cardinality']:failures.append('domain_cardinality:'+d)
        low,high=contract['assertion_median_by_domain'][d]
        if not group or not low<=statistics.median(r['assertion_count'] for r in group)<=high:failures.append('assertion_median:'+d)
        for metric,key in (('semantic_distractor','distractor'),('hidden_constraint','hidden_constraint')):
            if bydomain_semantic[d][metric]<contract['semantic_targets'][key+'_minimum_by_domain'][d]:failures.append('semantic_domain:'+d+':'+metric)
    if dict(card)!=contract['global_scorer_app_cardinality']:failures.append('global_cardinality')
    for apps,n in combos.items():
        if n>combo_cap(apps,contract):failures.append('combination_cap:'+'+'.join(apps))
    app_rows=[]
    for spec in contract['application_targets']:
        n=(B if spec['role']=='non_target_background_initial' else S)[spec['app']]
        if not spec['target_min']<=n<=spec['target_max']:failures.append('application:'+spec['app'])
        app_rows.append(dict(spec,selected_count=n,gap=max(0,spec['target_min']-n)))
    for a,n in contract['undercovered_initial_state_app_minimum'].items():
        if I[a]<n:failures.append('initial_minimum:'+a)
    for a,f in contract['concentration_caps']['initial_state_app_membership_fraction'].items():
        if I[a]>math.floor(f*N):failures.append('initial_cap:'+a)
    for group,spec in contract['undercovered_initial_state_union_minimum'].items():
        if sum(bool(set(r['initial_apps'])&set(spec['apps'])) for r in rows)<spec['minimum']:failures.append('initial_union:'+group)
    lengths=sorted(r['prompt_chars'] for r in rows);limits=contract['prompt_user_chars']
    if not lengths or not limits['median_min']<=statistics.median(lengths)<=limits['median_max']:failures.append('prompt_median')
    if lengths and lengths[math.ceil(.75*len(lengths))-1]>limits['p75_max']:failures.append('prompt_p75')
    if any(r['prompt_chars']>limits['per_item_max'] or r['assertion_count']>contract['assertion_per_item_max'] for r in rows):failures.append('single_item_size')
    novel=sum('+'.join(r['scorer_apps']) not in old_combinations for r in rows)
    if novel<math.ceil(N*contract['novelty_against_old_pool']['scorer_app_combination_absent_fraction_min']):failures.append('novel_application_combination')
    if semantic['new_semantic_family']<math.ceil(N*contract['novelty_against_old_pool']['fine_grained_semantic_family_absent_fraction_min']):failures.append('novel_semantic_family')
    return {'passed':not failures,'failures':dict(Counter(failures)),'actual_independent_roots':len(roots),
        'domain_counts':dict(domain),'scorer_cardinality':dict(card),'application_targets':app_rows,
        'semantic_confirmed':dict(semantic),'semantic_unknown':dict(unknown),
        'old_pool_absent_combination_count':novel,'released':False,'training_ready':False}


def audit_release_slices(records, contract, old_combinations, slice_contract=None):
    """Audit the actual recorded slices; never reorder rows to conceal drift."""
    result = audit(records, contract, old_combinations)
    if contract['total'] != N:
        return result
    if not slice_contract or slice_contract.get('total') != N:
        result['passed'] = False
        result['failures']['missing_bound_6k_slice_contract'] = 1
        return result
    groups = {i: [] for i in range(3)}
    invalid = 0
    for row in records:
        index = row.get('release_slice_index')
        if type(index) is not int or index not in groups:
            invalid += 1
        else:
            groups[index].append(row)
    if invalid:
        result['passed'] = False
        result['failures']['missing_or_invalid_release_slice_identity'] = invalid
    result['release_slices'] = []
    for index, group in groups.items():
        checked = audit(group, slice_contract, old_combinations)
        result['release_slices'].append({'release_slice_index': index, **checked})
        if not checked['passed']:
            result['passed'] = False
            result['failures']['release_slice:' + str(index)] = 1
    return result
