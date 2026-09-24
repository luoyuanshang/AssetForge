"""Cold binding of R177's native evidence and stable worksheet obligations."""

ENV = 'QA18K_THREEAPP_NATIVE_READ_PROFILE'
CONTRACT = 'r177-two-native-private-sources-stable-sheet-parent-cold-v1'

BASE = {
    'application_count': 3,
    'public_request_char_max': 1500,
    'strict_minimum_private_evidence_sources': 2,
    'strict_minimum_meaningful_state_changes': 2,
    'strict_named_gate_causal_services': True,
    'strict_cross_app_evidence_dataflow': True,
    'strict_final_state_observability': True,
    'strict_bounded_sibling_preservation': True,
}
ADDITIONS = {
    'strict_native_evidence_readability': True,
    'strict_google_sheets_scored_row_parent_identity': True,
    'three_app_native_read_contract': CONTRACT,
}
GROUPS = [
    ['jira', 'asana', 'monday', 'trello', 'pipefy', 'basecamp3'],
    ['google_sheets', 'google_drive', 'google_calendar', 'calendly'],
    ['docusign', 'bamboohr', 'recruitee', 'intercom', 'gorgias'],
]


def _validate_base(profile):
    if (any(profile.get(k) != v for k, v in BASE.items())
            or profile.get('application_groups_exactly_one') != GROUPS):
        raise ValueError('incomplete R177 native-read base profile')


def bind_profile(normalized, inherited):
    clauses = (
        'operations named-dual-gate closed-state workflow rubric',
        'exactly three causally necessary simulated applications',
        'each evidence record must be reachable through a working native read using information available from the public request and previously returned native data.',
        'the returned value must be the same scalar used by the scorer.',
        'the positive construction must begin from reset, retrieve both private values through the supported native surfaces',
        'every requested destination must be exact enough to distinguish a specific object, worksheet, row, cell',
        'bind target effects to the target’s stable identity and required final fields;',
    )
    if not all(clause in normalized for clause in clauses):
        raise ValueError('R177 cold native-read profile requires the complete observed obligation bundle')
    _validate_base(inherited)
    return dict(ADDITIONS)


def validate_profile(profile):
    _validate_base(profile)
    if any(profile.get(k) != v for k, v in ADDITIONS.items()):
        raise ValueError('incomplete R177 native-read execution profile')
