"""Bind the full observed R54 bounds for new cold four-application Authors."""
import re

ENV = 'QA18K_FOURAPP_R54_PROFILE'
CONTRACT = 'r54-four-native-groups-three-source-three-scalar-cold-v1'


def bind_profile(normalized, inherited):
    required = (
        'exactly four causally necessary simulated applications',
        'three applications must each supply a different undisclosed exact scalar '
        'that determines an exact final-state value in another application.',
        'require two to four real persistent effects and at least three scalar changes.',
        'never use a not-equals assertion as a substitute for preserving an original sibling value.',
        'keep the request normally 300–750 characters and never above 1500.',
        'no action, omission of an application',
    )
    if not all(clause in normalized for clause in required):
        raise ValueError('R54 cold profile requires the complete observed four-app obligation bundle')
    clause = re.search(r'\buse one (.+?)\. identify a bounded ', normalized)
    groups = [re.findall(r'`([a-z][a-z0-9_]*)`', part)
              for part in clause.group(1).split(';')] if clause else []
    if (len(groups) != 4 or any(not group for group in groups)
            or inherited.get('application_count') != 4
            or sorted({app for group in groups for app in group}) != inherited.get('permitted_applications')
            or sum(map(len, groups)) != len(set(sum(groups, [])))):
        raise ValueError('R54 four distinct native application groups must match the original allowlist')
    return dict(application_groups_exactly_one=groups, public_request_char_max=1500,
                strict_minimum_private_evidence_sources=3,
                strict_named_gate_causal_services=True, strict_cross_app_evidence_dataflow=True,
                strict_native_evidence_readability=True,
                strict_minimum_meaningful_state_changes=3,
                strict_final_state_observability=True, strict_bounded_sibling_preservation=True,
                four_app_r54_contract=CONTRACT)


def validate_profile(profile):
    expected = {'application_count':4, 'public_request_char_max':1500,
                'strict_minimum_private_evidence_sources':3,
                'strict_named_gate_causal_services':True, 'strict_cross_app_evidence_dataflow':True,
                'strict_native_evidence_readability':True,
                'strict_minimum_meaningful_state_changes':3,
                'strict_final_state_observability':True, 'strict_bounded_sibling_preservation':True,
                'four_app_r54_contract':CONTRACT}
    if any(profile.get(key) != value for key, value in expected.items()):
        raise ValueError('incomplete R54 cold execution profile')
    groups = profile.get('application_groups_exactly_one', [])
    if (len(groups) != 4 or any(not group for group in groups)
            or sorted(set(sum(groups, []))) != profile.get('permitted_applications')
            or sum(map(len, groups)) != len(set(sum(groups, [])))):
        raise ValueError('incomplete R54 native application grouping')
