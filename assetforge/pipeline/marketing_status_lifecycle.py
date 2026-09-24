"""Cold construction checks for R138; official evaluation/scoring stays unchanged."""
import copy
import re

CONTRACT = 'google-ads-forward-lifecycle-and-coupled-policy-v1'
GUIDANCE = (
    'All target and protected sibling reset statuses must be ENABLED or PAUSED. '
    'REMOVED is terminal: no positive, alternate, or negative construction program may edit '
    'a campaign after it becomes REMOVED, including within one batched operations request. '
    'Build counterexamples from clean reset, or use oracle_complete only when the challenged '
    'objects have not been removed. Preserve status as the required effect without a public '
    'only-status/no-other-field-change prohibition. Include a single-fact policy fixture that '
    'changes at least two target outcomes relative to the baseline, witnessing a coupled branch.'
)


def bind_profile(normalized):
    if '## status lifecycle feasibility' not in normalized:
        return {}
    required = [
        'a target campaign that must be updated cannot reset as `removed`',
        'all negative cases must be reachable through valid forward transitions from a clean reset',
        'the two protected siblings must also begin in states from which the required challenge mutations are genuinely executable',
        'at least one meaningful precedence, exception, relationship, or shared condition must affect multiple target results',
    ]
    if not all(s in normalized for s in required):
        raise ValueError('lifecycle profile requires the complete observed Author contract')
    return dict(strict_marketing_status_lifecycle=True, marketing_status_lifecycle_contract=CONTRACT)


def execute_checked(official, seed, actions, *, label):
    """Run unchanged native dispatch with per-object assignment guards for construction.

    The guard is confined to this diagnostic world. No official class, route,
    scorer, or solver world is patched; batched updates retain native ordering.
    """
    from .official_task_package import _execute_official_action_sequence
    world = official['WorldState'](**copy.deepcopy(seed))
    world.meta.allowed_services = ['ads_app']
    if not world.ads_app.campaigns:
        raise ValueError('lifecycle construction needs seeded campaigns')
    campaign_type = type(world.ads_app.campaigns[0])

    class ConstructionCampaign(campaign_type):
        def __setattr__(self, name, value):
            if name in type(self).model_fields and self.__dict__.get('status') == 'REMOVED':
                raise ValueError('lifecycle construction cannot edit or restore a REMOVED campaign')
            super().__setattr__(name, value)

    world.ads_app.campaigns = [ConstructionCampaign.model_validate(c.model_dump())
                                for c in world.ads_app.campaigns]
    receipts, _ = _execute_official_action_sequence(
        official=official, world=world, actions=actions, label=label)
    return len(receipts)


def validate_source(*, initial_state, assertions, oracle_actions, fixtures, cases,
                    forbidden_extra_actions, scorer_counterexample_tests, instruction):
    from . import official_task_package as p
    official = p._official_imports()
    if set(initial_state) != {'ads_app'}:
        raise ValueError('lifecycle shape must remain a single Google Ads application')
    campaigns = official['WorldState'](**copy.deepcopy(initial_state)).ads_app.campaigns
    if any(c.status not in {'ENABLED', 'PAUSED'} for c in campaigns):
        raise ValueError('lifecycle reset targets and challengeable siblings cannot be REMOVED')
    if re.search(r'(?i)\b(?:change only status|only status|modify no other fields|no other target changes)\b', instruction):
        raise ValueError('public only-status protection exceeds the available ID-status scorer')
    if not isinstance(fixtures, list) or len(fixtures) < 3:
        raise ValueError('lifecycle source requires the three independent policy fixtures')
    programs = [('baseline', initial_state, oracle_actions)]
    baseline = {a['campaign_id']: a['status'] for a in assertions}
    coupled = False
    for i, row in enumerate(fixtures):
        seed = copy.deepcopy(initial_state)
        for pointer, value in row['initial_state_replacements'].items():
            parts = p._json_pointer_parts(pointer); parent = seed
            for part in parts[:-1]:
                parent = parent[int(part)] if isinstance(parent, list) else parent[part]
            key = int(parts[-1]) if isinstance(parent, list) else parts[-1]
            parent[key] = copy.deepcopy(value)
        if any(c.status not in {'ENABLED', 'PAUSED'} for c in official['WorldState'](**seed).ads_app.campaigns):
            raise ValueError('alternate lifecycle reset cannot contain removed targets or siblings')
        expected = copy.deepcopy(assertions)
        for index, assertion in row['assertion_replacements'].items():
            expected[int(index)] = assertion
        # ID/role and single-scalar checks also run in the original cohort/fact
        # gates. This checks the new shared-policy outcome witness, not prose.
        changes = sum(a['status'] != baseline[a['campaign_id']] for a in expected)
        coupled |= changes >= 2
        programs.append((f'fixture_{i}', seed, row['oracle_actions']))
    if not coupled:
        raise ValueError('coupled policy needs one single-fact fixture changing at least two target outcomes')
    for i, action in enumerate(forbidden_extra_actions):
        programs.append((f'forbidden_{i}', initial_state, [*oracle_actions, action]))
    for kind, group in [('native', cases or []), ('matrix', scorer_counterexample_tests or [])]:
        for i, row in enumerate(group):
            if row['start_state'] not in {'initial', 'oracle_complete'}:
                raise ValueError('invalid lifecycle case reset boundary')
            actions = [copy.deepcopy(oracle_actions[a['oracle_index']])
                       if set(a) == {'oracle_index'} else copy.deepcopy(a) for a in row['actions']]
            if row['start_state'] == 'oracle_complete':
                actions = [*oracle_actions, *actions]
            programs.append((f'{kind}_{i}', initial_state, actions))
    calls = sum(execute_checked(official, seed, actions, label='lifecycle_' + name)
                for name, seed, actions in programs)
    return dict(contract=CONTRACT, checked_programs=len(programs), checked_native_calls=calls,
                coupled_single_fact_witness=True, runtime_or_scorer_modified=False,
                construction_only=True, policy_business_meaning_requires_independent_review=True)
