"""Cold binding of the original Sales five-application obligations."""
import re
from .hr_five_app_profile import GUIDANCE

ENV = 'QA18K_SALES_FIVEAPP_PROFILE'
CONTRACT = 'sales-five-app-four-private-sources-three-changes-two-native-conditions-v1'


def bind_profile(normalized, profile):
    required = (
        '# sales five-application workflow rubric',
        'exactly five causally necessary simulated applications',
        'require at least three genuine joins and two jointly necessary policy or exception conditions.',
        'four applications must supply distinct private evidence values to exact scored results in other applications.',
        'mirror fields and reverse links must not replace an intended source.',
        'require two to four real native persistent effects and at least three scalar changes.',
        'include native assertion coverage for every participating application.',
        'protect the same original records against deletion, swaps and altered protected fields.',
        'keep the request normally 300–750 characters and below1500.',
        'require final observable results only, not reads, routes, intermediate states, private history or hidden formatting.',
    )
    if not all(clause in normalized for clause in required):
        raise ValueError('Sales five-app profile requires the complete observed Author obligation bundle')
    clause = re.search(r'select a crm (.+?)\. use contract eligibility', normalized)
    groups = [re.findall(r'`([a-z0-9_]+)`', part)
              for part in re.findall(r'\(([^)]+)\)', clause.group(1))] if clause else []
    expected = [['salesforce','hubspot'], ['docusign','google_drive'],
                ['calendly','google_calendar'], ['google_sheets','airtable'],
                ['jira','asana','monday','gmail','slack']]
    if (groups != expected or profile.get('application_count') != 5
            or sorted(set(sum(groups, []))) != profile.get('permitted_applications')):
        raise ValueError('Sales five-app source application groups changed')
    return dict(application_groups_exactly_one=groups, public_request_char_max=1499,
                strict_minimum_private_evidence_sources=4, strict_named_gate_causal_services=True,
                strict_cross_app_evidence_dataflow=True, strict_unique_private_evidence_values=True,
                strict_native_evidence_readability=True, strict_minimum_meaningful_state_changes=3,
                strict_final_state_observability=True, strict_minimum_native_join_pairs=3,
                strict_native_join_service_count=5, strict_opposite_policy_fixture=True,
                strict_minimum_policy_fixtures=2, strict_sales_fiveapp_policy_conditions=True,
                sales_fiveapp_contract=CONTRACT)
