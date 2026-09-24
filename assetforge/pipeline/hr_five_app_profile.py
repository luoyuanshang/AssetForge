"""Cold binding of the complete HR five-application Author obligations."""
import re

ENV = 'QA18K_HR_FIVEAPP_PROFILE'
CONTRACT = 'hr-five-app-four-private-sources-three-changes-two-native-conditions-v1'
GUIDANCE = (
    'Bind all five applications in the existing selection_contract so that candidate-private '
    'native record identifiers form a connected graph with at least three application pairs. '
    'Provide 2-4 policy_fixtures for the two jointly necessary conditions. Each fixture changes '
    'exactly one existing scalar, and different fixtures change different scalar leaves. '
    'Base oracle GET probes must expose each changed scalar and its replacement at the same '
    'native response leaf in independent reset worlds without taking either value as input. '
    'Recompute the legitimate outcome under the same public rule; both correct action paths '
    'must fail in the opposite world. These are construction witnesses, not required solver '
    'reads or action order. Business meaning and condition independence still require review.'
)


def bind_profile(normalized, profile):
    required = [
        'exactly five causally necessary simulated applications',
        'at least three genuine cross-application joins and two jointly necessary policy or exception conditions',
        'four applications must each contribute a distinct private evidence value to an exact scored result elsewhere',
        'two to four native persistent effects with at least three scalar changes',
        'mirrored employee ids, copied decisive values or a second reverse link must not make any source dispensable',
        'readable from the reset world through that application’s official native read surface',
        'the same original records must remain identifiable and protected against deletion, swaps and altered protected fields',
        'judge only final observable obligations, not read order, routes, intermediate states, private action history or hidden formatting',
    ]
    if not all(clause in normalized for clause in required):
        raise ValueError('HR five-app cold profile requires the complete observed Author obligation bundle')
    group_clause = re.search(r'select a people system (.+?)\. construct an ', normalized)
    groups = [re.findall(r'`([a-z0-9_]+)`', group)
              for group in re.findall(r'\(([^)]+)\)', group_clause.group(1))] if group_clause else []
    expected = [['bamboohr','recruitee'], ['google_drive','docusign'],
                ['calendly','google_calendar'], ['google_sheets','airtable','jira','asana','monday'],
                ['gmail','slack']]
    if groups != expected or profile.get('application_count') != 5:
        raise ValueError('HR five-app source application groups changed')
    return dict(application_groups_exactly_one=groups, public_request_char_max=1500,
        strict_minimum_private_evidence_sources=4, strict_named_gate_causal_services=True,
        strict_cross_app_evidence_dataflow=True, strict_unique_private_evidence_values=True,
        strict_native_evidence_readability=True, strict_minimum_meaningful_state_changes=3,
        strict_final_state_observability=True, strict_minimum_native_join_pairs=3,
        strict_native_join_service_count=5, strict_opposite_policy_fixture=True,
        strict_minimum_policy_fixtures=2, strict_hr_fiveapp_policy_conditions=True,
        hr_fiveapp_contract=CONTRACT)
