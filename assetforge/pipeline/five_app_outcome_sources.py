"""Cold five-app binding: necessity may select a target or supply its result."""
ENV = 'QA18K_FIVEAPP_OUTCOME_SOURCE_PROFILE'
CONTRACT = 'five-app-native-private-output-or-selection-necessity-v1'
GUIDANCE = (
    'Candidate bindings may identify both eligibility evidence and private output sources. '
    'An application with independently native-readable, source-exclusive private scalars '
    'carried into exact scored mutations elsewhere need not independently eliminate a '
    'candidate. Repeated join keys alone never establish this output-source role. Keep '
    'the unique final winner, no singleton predicate shortcut, public rules, connected '
    'five-application graph, four private sources, three changed scalars, and two '
    'independent native policy conditions. A merely redundant eligibility flag without '
    'that independent output witness still fails.'
)


def validate_profile(profile):
    if not (profile.get('strict_hr_fiveapp_policy_conditions')
            or profile.get('strict_marketing_fiveapp_policy_conditions')
            or profile.get('strict_sales_fiveapp_policy_conditions')):
        raise ValueError('outcome-source binding requires complete HR, Marketing or Sales five-app profile')
    expected = dict(application_count=5, strict_minimum_private_evidence_sources=4,
        strict_minimum_meaningful_state_changes=3, strict_minimum_native_join_pairs=3,
        strict_native_join_service_count=5, strict_minimum_policy_fixtures=2,
        strict_named_gate_causal_services=True, strict_unique_private_evidence_values=True,
        strict_native_evidence_readability=True, strict_cross_app_evidence_dataflow=True,
        strict_opposite_policy_fixture=True)
    if any(profile.get(k) != v for k, v in expected.items()):
        raise ValueError('outcome-source binding lost original five-app obligations')


def witnessed_sources(*, instruction, initial_state, oracle_actions, assertions):
    from .official_task_package import (
        _validate_strict_named_gate_causal_services, _validate_native_evidence_readability)
    values = dict(instruction=instruction, initial_state=initial_state,
        oracle_actions=oracle_actions, assertions=assertions, minimum_source_services=4)
    flow = _validate_strict_named_gate_causal_services(**values, require_unique_source_values=True)
    reads = _validate_native_evidence_readability(**values)
    return frozenset(flow['private_evidence_source_services']) & frozenset(reads['readable_source_services'])
