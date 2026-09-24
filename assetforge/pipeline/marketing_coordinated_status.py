"""Cold Google Ads status-cohort gate; business policy remains independently reviewed."""
import copy
import re

CONTRACT='google-ads-two-or-three-target-statuses-two-siblings-v1'
GUIDANCE=(
    'This task uses only Google Ads campaigns: exactly two or three distinct existing target IDs '
    'each need one status change, plus exactly two non-target campaign IDs with unchanged statuses. '
    'Give each campaign exactly one ads_app_campaign_status assertion with campaign_id and status; '
    'do not use mutable-name matchers or extra scoring flags. All base and alternate correct paths '
    'must mutate only campaign statuses and preserve campaign IDs and other fields. All fixtures '
    'retain the same target/sibling roles and reset statuses, and produce pairwise distinct full '
    'target-status vectors. Each target status differs from reset in every correct world. '
    'Only official campaign mutate POSTs may be used as writes; no tags, names or member operations.'
)


def bind_profile(rubric,normalized):
    from .single_app_policy_facts import _execution_profile
    match=re.search(r'exactly one causally necessary simulated application chosen from ([^.]+)\.',rubric,re.I)
    if not match or set(re.findall(r'`([a-z][a-z0-9_]*)`',match.group(1)))!={'mailchimp','buffer','ads_app'}:
        raise ValueError('coordinated status requires the actual complete Marketing application clause')
    required=[
        'coordinate exactly two or three closely related existing google ads campaigns',
        'require exactly one persistent scalar update',
        'on each target campaign, for exactly two or three required updates in total',
        'use at least three distinct, private, natively readable scalar facts',
        'holding all other facts, identities, reset statuses, and obligations fixed',
        'changing only that fact must change the correct complete target-status vector',
        'the baseline completion must fail in every varied world',
        'each varied-world completion must fail in the baseline world',
        'outcome vectors must be pairwise distinguishable',
        'every required target status in the baseline and each scored fixture must differ',
        'seed exactly two non-target sibling campaigns',
        'every assertion must locate the campaign by immutable campaign id',
        'this rubric must be instantiated with',
    ]
    if not all(clause in normalized for clause in required):
        raise ValueError('coordinated status requires the complete observed R135 Author obligations')
    from .marketing_status_lifecycle import bind_profile as bind_lifecycle
    return dict(_execution_profile(['mailchimp','buffer','ads_app']),
        permitted_applications=['buffer','ads_app','mailchimp'],
        strict_native_fact_json_projection=True,strict_marketing_coordinated_status=True,
        marketing_coordinated_status_contract=CONTRACT, **bind_lifecycle(normalized))


def validate(initial_state,assertions,world=None,reference=None,actions=None,reset_campaigns=None):
    from .official_task_package import _official_imports
    official=_official_imports()
    if set(initial_state)!={'ads_app'}:
        raise ValueError('coordinated statuses require only the Google Ads application')
    base=official['WorldState'](**copy.deepcopy(initial_state))
    if world is not None and reset_campaigns is None:
        raise ValueError('native final comparison requires the actual pre-action campaign objects')
    campaigns=reset_campaigns if reset_campaigns is not None else base.ads_app.campaigns
    ids=[c.id for c in campaigns]
    if len(ids) not in (4,5) or len(set(ids))!=len(ids) or any(not i for i in ids):
        raise ValueError('coordinated statuses need 2-3 unique targets and exactly two sibling IDs')
    if len({c.account_id for c in campaigns})!=1 or not campaigns[0].account_id:
        raise ValueError('all coordinated targets and siblings must share one explicit account')
    expected={}
    for assertion in assertions:
        if (not isinstance(assertion,dict) or set(assertion)!={'type','campaign_id','status'}
                or assertion['type']!='ads_app_campaign_status'
                or assertion['campaign_id'] not in ids or assertion['campaign_id'] in expected
                or assertion['status'] not in {'ENABLED','PAUSED','REMOVED'}):
            raise ValueError('each campaign needs one exact ID-bound status assertion without name or extra flags')
        expected[assertion['campaign_id']]=assertion['status']
    if set(expected)!=set(ids):raise ValueError('every target and sibling requires its own status assertion')
    reset={c.id:c.status for c in campaigns}
    targets=sorted(i for i in ids if reset[i]!=expected[i]);siblings=sorted(set(ids)-set(targets))
    if len(targets) not in (2,3) or len(siblings)!=2:
        raise ValueError('every correct world needs 2-3 changed target statuses and exactly two unchanged siblings')
    if reference and (targets!=reference['target_ids'] or siblings!=reference['sibling_ids'] or reset!=reference['reset_statuses']):
        raise ValueError('counterfactual target/sibling roles and reset statuses must remain fixed')
    if actions is not None:
        for action in actions:
            method=str(action.get('method','GET')).upper()
            if method=='GET':continue
            if method!='POST' or not action.get('url','').endswith('/campaigns:mutate'):
                raise ValueError('only native campaign status mutations may implement coordinated effects')
    if world is not None:
        actual=world.ads_app.campaigns
        if [c.id for c in actual]!=ids:raise ValueError('campaign identities or collection changed during completion')
        for before,after in zip(campaigns,actual):
            old=before.model_dump(mode='json');new=after.model_dump(mode='json')
            old.pop('status');new.pop('status')
            if old!=new:raise ValueError('coordinated correct completion changed a non-status campaign field')
            if after.status!=expected[after.id]:raise ValueError('native final status differs from its ID-bound obligation')
    return dict(contract=CONTRACT,target_ids=targets,sibling_ids=siblings,reset_statuses=reset,
        status_vector=[expected[i] for i in targets],policy_semantics_require_independent_review=True)
