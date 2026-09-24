"""Count-feasible candidate reservations, separate from collection authorization.

Scoring membership comes from the full pinned registry. Existing QA and
hypothetical completion slots are never merged into a released task list.
"""
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_FLOOR
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import statistics
from .application_distribution import namespace, task_membership, task_info, COMMIT, ROOT


def bound_bytes(ref):
    p=(ROOT/ref['path']).resolve();p.relative_to(ROOT)
    raw=p.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ref['sha256']:
        raise ValueError('bound input hash mismatch: '+ref['path'])
    return raw


def read_bound(ref):
    return json.loads(bound_bytes(ref))


def user_chars(task):
    prompt=task.get('prompt',[])
    if isinstance(prompt,str):return len(prompt)
    texts=[]
    for m in prompt:
        if m.get('role')!='user':continue
        content=m.get('content','')
        if isinstance(content,str):texts.append(content)
        elif isinstance(content,list):texts.extend(p.get('text','') for p in content if isinstance(p,dict))
    return len('\n'.join(texts))


def combo_cap(apps,contract):
    # Integer caps are authoritative when the contract carries them; the fraction
    # fields stay for historical contracts.  Using the integers avoids float
    # rounding drift (floor(0.1993*N)=1195 for a 1196 cap).
    caps=contract['concentration_caps']
    if len(apps)==2:
        cap=caps.get('two_app_combination_max')
        if cap is None:cap=int((Decimal(str(caps['any_two_app_combination_fraction']))*contract['total']).to_integral_value(rounding=ROUND_FLOOR))
    else:
        cap=caps.get('exact_scorer_combination_max')
        if cap is None:cap=int((Decimal(str(caps['any_scorer_app_combination_fraction']))*contract['total']).to_integral_value(rounding=ROUND_FLOOR))
    key='+'.join(sorted(apps))
    specific_int=caps.get('specific_combination_max',{}).get(key)
    if specific_int is None:
        specific=caps.get('specific_combination_fraction',{}).get(key)
        if specific is not None:
            specific_int=int((Decimal(str(specific))*contract['total']).to_integral_value(rounding=ROUND_FLOOR))
    if specific_int is not None:
        cap=min(cap,specific_int)
    return cap


def candidate(row,binding,contract,known,held):
    root=binding.get('root_task_id');source=binding.get('source_sha256')
    if not root or not source or row.get('source_sha256')!=source or row.get('root_task_id')!=root:
        raise ValueError('source/root identity mismatch')
    if binding.get('target_commit')!=COMMIT or binding.get('protocol_sha256')!=contract['official_reference']['protocol']['sha256']:
        raise ValueError('runtime protocol mismatch')
    if binding.get('accepted_v106') is not True or binding.get('quality_holds'):
        raise ValueError('missing acceptance or unresolved hold')
    ancestry={root,binding.get('task_id'),*(r.get('task_id') for r in binding.get('historical_lineage',[]))}
    if held & ancestry:raise ValueError('unresolved ancestral quality hold')
    task=binding['target_task'];info=task_info(task);membership=task_membership(task,known)
    scored=membership['scorer_apps'];domain=binding['domain']
    if domain not in contract['domain_targets'] or str(len(scored)) not in contract['domain_targets'][domain]['scorer_app_cardinality']:
        raise ValueError('outside domain/cardinality target')
    n=len(info.get('assertions',[]));length=user_chars(task)
    if n>contract['assertion_per_item_max'] or length>contract['prompt_user_chars']['per_item_max']:
        raise ValueError('single-item size limit exceeded')
    return {'root_task_id':root,'source_sha256':source,'binding':row['binding'],
        'domain':domain,'application_count':len(scored),'applications':list(scored),
        'initial_applications':list(membership['initial_apps']),'assertion_count':n,
        'prompt_user_chars':length,'semantic_eligibility':'not_verified_by_count_selection'}


def solve(candidates,contract,old_combos,seconds=120):
    from ortools.sat.python import cp_model
    from assetforge.tools.freeze_application_distribution_contract import DOMAINS
    if not 1<=seconds<=600:raise ValueError('bounded solver budget required')
    m=cp_model.CpModel();bycell=defaultdict(list);bycombo=defaultdict(list);byS=defaultdict(list)
    byI=defaultdict(list);byroot=defaultdict(list);bysource=defaultdict(list)
    future_by_domain=defaultdict(list);future_byS=defaultdict(list);future=[];existing=[];novel=[]
    union=defaultdict(list);N=contract['total'];rng=random.Random(17092026)
    def register(d,apps,initial,x):
        apps=tuple(sorted(apps));bycell[d,str(len(apps))].append(x);bycombo[apps].append(x)
        for a in apps:byS[a].append(x)
        for a in initial:byI[a].append(x)
        if '+'.join(apps) not in old_combos:novel.append(x)
        for group,spec in contract['undercovered_initial_state_union_minimum'].items():
            if set(initial)&set(spec['apps']):union[group].append(x)
    for i,r in enumerate(candidates):
        x=m.NewBoolVar('candidate:'+str(i));existing.append(x)
        byroot[r['root_task_id']].append(x);bysource[r['source_sha256']].append(x)
        register(r['domain'],r['applications'],r['initial_applications'],x)
    for vs in [*byroot.values(),*bysource.values()]:m.Add(sum(vs)<=1)
    for d,apps_text in DOMAINS.items():
        apps=sorted(apps_text.split())
        for k,target in contract['domain_targets'][d]['scorer_app_cardinality'].items():
            choices=list(itertools.combinations(apps,int(k)))
            if int(k)>2 and len(choices)>900:choices=rng.sample(choices,900)
            for combo in sorted(choices):
                x=m.NewIntVar(0,min(target,combo_cap(combo,contract)),'future:'+d+':'+','.join(combo))
                future.append((d,combo,x));future_by_domain[d].append(x)
                for a in combo:future_byS[a].append(x)
                register(d,combo,combo,x)
    for d,spec in contract['domain_targets'].items():
        for k,count in spec['scorer_app_cardinality'].items():m.Add(sum(bycell[d,k])==count)
    for combo,vs in bycombo.items():m.Add(sum(vs)<=combo_cap(combo,contract))
    future_total=sum(x for _,_,x in future)
    overlays={}
    for a in set(contract['undercovered_initial_state_app_minimum'])|{'mailbox_app'}:
        # Only as yet ungenerated slots may acquire these I-only roles. This is
        # a count witness, not a fabricated readable entity or completed QA.
        x=m.NewIntVar(0,N,'future_initial_only:'+a);overlays[a]=x
        m.Add(x<=future_total-sum(future_byS[a]));byI[a].append(x)
    deviations=[]
    for r in contract['application_targets']:
        count=sum((byI if r['role']=='non_target_background_initial' else byS)[r['app']])
        m.Add(count>=r['target_min']);m.Add(count<=r['target_max'])
        diff=m.NewIntVar(0,N,'deviation:'+r['app']);m.AddAbsEquality(diff,count-r['target_preferred']);deviations.append(diff)
    for a,n in contract['undercovered_initial_state_app_minimum'].items():m.Add(sum(byI[a])>=n)
    for a,f in contract['concentration_caps']['initial_state_app_membership_fraction'].items():
        m.Add(sum(byI[a])<=math.floor(float(f)*N))
    # No double-counted mailbox_app overlay is needed to satisfy union lower bounds:
    # the S-backed union itself must satisfy each minimum.
    for group,spec in contract['undercovered_initial_state_union_minimum'].items():m.Add(sum(union[group])>=spec['minimum'])
    m.Add(sum(novel)>=math.ceil(N*contract['novelty_against_old_pool']['scorer_app_combination_absent_fraction_min']))
    for d,spec in contract['domain_targets'].items():
        low,high=contract['assertion_median_by_domain'][d];half=spec['total']//2+1
        for predicate in (lambda n:n>=low,lambda n:n<=high):
            m.Add(sum(x for r,x in zip(candidates,existing) if r['domain']==d and predicate(r['assertion_count']))+
                  sum(future_by_domain[d])>=half)
    limits=contract['prompt_user_chars']
    for predicate,required in [(lambda n:n>=limits['median_min'],N//2+1),
        (lambda n:n<=limits['median_max'],N//2+1),(lambda n:n<=limits['p75_max'],math.ceil(N*.75))]:
        m.Add(sum(x for r,x in zip(candidates,existing) if predicate(r['prompt_user_chars']))+future_total>=required)
    # Root reuse first; reference proximity breaks ties. Future sizes have a
    # feasible in-band assignment; their actual task sizes are not yet measured.
    weight=N*len(contract['application_targets'])+1
    m.Maximize(weight*sum(existing)-sum(deviations))
    solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=seconds;solver.parameters.num_search_workers=8
    status=solver.Solve(m);passed=status in (cp_model.OPTIMAL,cp_model.FEASIBLE)
    report={'count_completion_feasible':passed,'solver_status':solver.StatusName(status),
        'solver_wall_seconds':solver.WallTime(),'optimal':status==cp_model.OPTIMAL,
        'collection_authorized':False,'semantic_constraints_verified':False,'distribution_valid':False,
        'released':False,'training_ready':False,'provider_calls':0}
    if not passed:return dict(report=report,items=[],planned_candidates=[],future_count_allocation=[])
    planned=[r for r,x in zip(candidates,existing) if solver.Value(x)]
    allocation=[dict(domain=d,scorer_apps=list(apps),count=solver.Value(x)) for d,apps,x in future if solver.Value(x)]
    report.update(planned_candidate_roots=len(planned),future_root_gap=N-len(planned),
        candidate_cell_counts=dict(Counter(r['domain']+':'+str(r['application_count']) for r in planned)),
        objective=solver.ObjectiveValue(),best_objective_bound=solver.BestObjectiveBound(),
        candidate_assertion_medians={d:statistics.median([r['assertion_count'] for r in planned if r['domain']==d])
            if any(r['domain']==d for r in planned) else None for d in contract['domain_targets']},
        upper_bound_only='Native/semantic/current-contract eligibility still requires review; hypothetical slots are not QA.')
    application_table=[]
    for r in contract['application_targets']:
        app=r['app'];initial=r['role']=='non_target_background_initial'
        count=sum(app in row['initial_applications' if initial else 'applications'] for row in planned)
        application_table.append(dict(app=app,role=r['role'],reference_count=r['reference_count'],reference_denominator=r['denominator'],
            target_min=r['target_min'],target_max=r['target_max'],planned_candidate_count=count,
            actual_collection_selected_count=0,lower_gap=max(0,r['target_min']-count),
            completion_count=solver.Value(sum((byI if initial else byS)[app]))))
    return dict(report=report,items=[],planned_candidates=planned,future_count_allocation=allocation,
        future_initial_only_counts={a:solver.Value(x) for a,x in overlays.items()},application_targets=application_table)
