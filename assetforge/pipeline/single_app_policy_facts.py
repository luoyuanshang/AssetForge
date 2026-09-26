"""Construction-only proof of three distinct, private, native-readable facts."""
import copy
import hashlib
import json
import re

CONTRACT = 'single-app-three-distinct-scalar-reset-read-counterfactual-v1'
GUIDANCE = (
    'For this single-application profile, provide at least three fixtures. Each '
    'changes exactly one different existing scalar JSON pointer. Include native '
    'GET probes in the base reference_actions that return each original fact from '
    'reset and its replacement from that separately reset alternate world. '
    'Do not disclose those values in the public request or GET arguments. '
    'The changed fact must remain visible at the same response leaf; an unrelated '
    'occurrence of its value does not prove that the seed field is readable.'
)
NATIVE_JSON_PROJECTION='official-world-json-scalar-v1'
PROJECTION_GUIDANCE=(
    'Native read witnesses compare the official WorldState JSON projection of '
    'each source scalar, including native numeric normalization. The two '
    'projected values must remain distinct; arbitrary string coercions are not allowed.'
)


def bind_profile(normalized):
    r127 = [
        'exactly one causally necessary simulated application',
        'at least three distinct, natively readable seeded facts',
        'each of the three facts must independently affect the selected outcome',
        'only that seeded scalar changes',
        'base result invalid in the counterfactual world',
        'counterfactual result invalid in the base world',
        'must not quote the decisive seeded values',
    ]
    # R128 is an independently authored, fully read next version. Bind its
    # complete equivalent obligation bundle; never accept isolated keywords or
    # silently weaken a historical frozen profile.
    r128 = [
        'exactly one causally necessary simulated application',
        'use three distinct, independently decisive seeded scalar facts',
        'all facts and policy rules must be reachable through official native reads',
        'each fact must materially affect the required terminal state',
        'only that fact changes',
        'the base outcome must be invalid in that world',
        'the counterfactual outcome must be invalid in the base world',
        'all other records, identities, distractors, and reset values must remain unchanged',
        'must not quote decisive seeded values',
    ]
    r134 = [text.replace('use three distinct,', 'use exactly three distinct,') for text in r128] + [
        'do not rely on an uncounted fourth case input',
        'they remain fixed policy state across the three single-fact worlds',
    ]
    if all(text in normalized for text in r134):
        return dict(_execution_profile(['google_sheets', 'google_calendar', 'docusign']),
                    strict_maximum_policy_fixtures=3)
    if not any(all(text in normalized for text in bundle) for bundle in (r127, r128)):
        raise ValueError('single-app three-fact cold profile requires the complete observed Author contract')
    return _execution_profile(['google_sheets', 'google_calendar', 'docusign'])


def bind_marketing_profile(normalized):
    required=[
        'exactly one causally necessary simulated application chosen from',
        'the three constraints must arise from distinct, private, natively readable scalar facts',
        'each causal fact independently matters',
        'holding the remaining state and obligations fixed',
        'a resettable variation of only that fact must change the correct branch or value',
        'make the baseline completion wrong in the varied world',
        'make the counterfactual completion wrong in the baseline world',
        'leaving the decisive seeded values to be discovered through official application reads',
        'require two or three persistent scalar updates',
    ]
    if not all(text in normalized for text in required):
        raise ValueError('Marketing three-fact profile requires the complete observed R133 Author contract')
    return dict(_execution_profile(['mailchimp', 'buffer', 'ads_app']),
        strict_native_fact_json_projection=True)


def _execution_profile(application_group):
    return dict(application_count=1,
        application_groups_exactly_one=[application_group],
        strict_opposite_policy_fixture=True, strict_minimum_policy_fixtures=3,
        strict_independent_readable_policy_facts=True,
        independent_policy_fact_contract=CONTRACT,
        strict_minimum_meaningful_state_changes=2)


SALES_ENV = 'QA18K_SALES_THREEFACT_PROFILE'
SALES_CONTRACT = 'sales-single-app-three-independent-native-scalar-facts-v1'


def bind_sales_profile(normalized, profile):
    required = [
        'sales single-application counterfactual-branch rubric',
        'exactly one causally necessary simulated application chosen from',
        'three distinct, privately seeded scalar facts',
        'require two or three persistent scalar updates on that existing record',
        'seed exactly two non-target sibling records',
        'only that existing seeded scalar changes',
        'keep the remaining seeded state and public obligations fixed',
        'the baseline completion must be wrong in that counterfactual world',
        'the counterfactual completion must be wrong in the baseline world',
        'native reads from reset must expose the original fact in the baseline',
        'its replacement at the same field in the alternate world',
        'the three worlds must change different scalar fields',
        'do not disclose the critical baseline fact values in the request or read arguments',
    ]
    if (not all(text in normalized for text in required)
            or profile.get('application_count') != 1
            or set(profile.get('permitted_applications', [])) != {'hubspot', 'salesforce'}):
        raise ValueError('Sales three-fact profile requires the complete observed R186 Author contract')
    return dict(_execution_profile(['hubspot', 'salesforce']),
                strict_native_fact_json_projection=True, sales_singleapp_fact_contract=SALES_CONTRACT)


def validate_sales_profile(profile):
    expected = dict(_execution_profile(['hubspot', 'salesforce']),
                    strict_native_fact_json_projection=True, sales_singleapp_fact_contract=SALES_CONTRACT)
    if (any(profile.get(key) != value for key, value in expected.items())
            or set(profile.get('permitted_applications', [])) != {'hubspot', 'salesforce'}):
        raise ValueError('incomplete Sales three-fact execution profile')


def _leaves(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _leaves(child, path+(key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _leaves(child, path+(index,))
    else:
        yield path, value


def _literal_present(text, value):
    token = ' '.join(str(value).split())
    if not token:
        return True
    return re.search(r'(?<!\w)'+re.escape(token)+r'(?!\w)',
        ' '.join(text.split()), re.IGNORECASE) is not None


def _public_fact_disclosed(text, value):
    """A numeric row locator does not disclose an unrelated numeric cell value.

    Keep strings and every other literal occurrence subject to the existing
    rule. This exception applies only to public prose, never GET arguments.
    """
    if type(value) is not int:
        return _literal_present(text, value)
    normalized = ' '.join(text.split())
    matches = re.finditer(r'(?<!\w)' + re.escape(str(value)) + r'(?!\w)', normalized)
    return any(not re.search(r'\brows?\s+$', normalized[:match.start()], re.IGNORECASE)
               for match in matches)


def validate(*, initial_state, fixtures, reference_actions, allowed_services, instruction,
             official, pointer_parts, canonical, native_json_projection=False,
             hr_fiveapp_conditions=False, marketing_fiveapp_conditions=False,
             sales_fiveapp_conditions=False):
    fiveapp_conditions = (hr_fiveapp_conditions, marketing_fiveapp_conditions, sales_fiveapp_conditions)
    if sum(bool(value) for value in fiveapp_conditions) > 1:
        raise ValueError('distinct five-app domain contracts cannot be combined')
    if any(fiveapp_conditions):
        if len(allowed_services) != 5 or len(set(allowed_services)) != 5 or not 2 <= len(fixtures) <= 4:
            raise ValueError('five-app condition gate requires five services and 2-4 fixtures')
    elif len(allowed_services) != 1 or not 3 <= len(fixtures) <= 4:
        raise ValueError('single-app native fact gate requires one service and 3-4 fixtures')
    prepared = []
    seen = set()
    for index, fixture in enumerate(fixtures):
        changes = fixture.get('initial_state_replacements', {}) if isinstance(fixture, dict) else {}
        if not isinstance(changes, dict) or len(changes) != 1:
            raise ValueError('each independent policy fixture must change exactly one scalar')
        pointer, new = next(iter(changes.items()))
        parts = pointer_parts(pointer)
        if not parts or parts[0] not in allowed_services:
            raise ValueError('policy fact must belong to an allowed application')
        alternate = copy.deepcopy(initial_state)
        parent = alternate
        normalized = []
        for offset, part in enumerate(parts):
            key = part
            if isinstance(parent, list):
                if not part.isdigit() or str(int(part)) != part or int(part) >= len(parent):
                    raise ValueError('policy fact requires a canonical existing list index')
                key = int(part)
            elif not isinstance(parent, dict) or key not in parent:
                raise ValueError('policy fact pointer does not exist')
            normalized.append(key)
            if offset == len(parts)-1:
                old = parent[key]
                if isinstance(old, (dict, list)) or isinstance(new, (dict, list)) or old == new:
                    raise ValueError('policy fact must change an existing scalar')
                if old is None or _public_fact_disclosed(instruction, old):
                    raise ValueError('decisive original policy fact is empty or disclosed in the public request')
                parent[key] = copy.deepcopy(new)
            else:
                parent = parent[key]
        identity = tuple(normalized)
        if identity in seen:
            raise ValueError('policy fixtures must change different scalar leaves, not multiple values of one fact')
        seen.add(identity)
        prepared.append((index, pointer, old, new, alternate))

    def read(seed, action):
        world = official['WorldState'](**copy.deepcopy(seed))
        world.meta.allowed_services = list(allowed_services)
        before = world.model_dump(mode='python')
        packed = lambda value: canonical(value) if isinstance(value, (dict, list)) else value
        raw = official['api_fetch'](world, 'GET', action['url'],
            params=packed(action.get('params')), body=packed(action.get('body')))
        response = json.loads(raw)
        if isinstance(response, dict) and response.get('error') is not None:
            raise ValueError('policy fact GET probe failed in a reset world')
        if world.model_dump(mode='python') != before:
            raise ValueError('policy fact GET probe mutated reset state')
        return dict(_leaves(response)), hashlib.sha256(raw.encode()).hexdigest()

    probes = [(i, a) for i, a in enumerate(reference_actions)
              if str(a.get('method', 'GET')).upper() == 'GET']
    base_reads = {i:read(initial_state,a) for i,a in probes}
    results = []
    for index, pointer, old, new, alternate in prepared:
        visible_old,visible_new=old,new
        if native_json_projection:
            def projected(seed):
                value=official['WorldState'](**copy.deepcopy(seed)).model_dump(mode='json')
                for part in pointer_parts(pointer):
                    value=value[int(part)] if isinstance(value,list) else value[part]
                return value
            visible_old,visible_new=projected(initial_state),projected(alternate)
            if (visible_old==visible_new or isinstance(visible_old,(dict,list))
                    or isinstance(visible_new,(dict,list))):
                raise ValueError('native policy fact projection did not change a scalar')
        witnesses = []
        for reference_index, action in probes:
            if _literal_present(canonical(action), old) or _literal_present(canonical(action), new):
                continue
            base, base_sha = base_reads[reference_index]
            changed, changed_sha = read(alternate, action)
            paths = [list(p) for p, value in base.items()
                if type(value) is type(visible_old) and value == visible_old and p in changed
                and type(changed[p]) is type(visible_new) and changed[p] == visible_new]
            if paths:
                witnesses.append(dict(reference_index=reference_index, response_paths=paths,
                    base_response_sha256=base_sha, alternate_response_sha256=changed_sha))
        if not witnesses:
            raise ValueError(f'policy_fixtures[{index}] has no native reset GET witness for its changed scalar')
        contract = CONTRACT
        if hr_fiveapp_conditions:
            from .hr_five_app_profile import CONTRACT as contract
        if marketing_fiveapp_conditions:
            from .marketing_five_app_profile import CONTRACT as contract
        if sales_fiveapp_conditions:
            from .sales_five_app_profile import CONTRACT as contract
        results.append(dict(contract=contract, fixture_index=index, changed_scalar_pointer=pointer,
            witnesses=witnesses, construction_only=True, solver_read_order_required=False,
            **({'native_scalar_projection':NATIVE_JSON_PROJECTION} if native_json_projection else {}),
            policy_semantic_fidelity_requires_independent_review=True))
    return results
