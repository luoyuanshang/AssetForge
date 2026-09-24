"""Complete cold Marketing five-app obligations, using existing native gates."""
import re
from .hr_five_app_profile import GUIDANCE

ENV='QA18K_MARKETING_FIVEAPP_PROFILE'
CONTRACT='marketing-five-app-four-private-sources-three-changes-two-native-conditions-v1'


def bind_profile(normalized,profile):
    required=[
        'exactly five causally necessary simulated applications',
        'require at least three genuine joins and two jointly necessary policy or exception conditions',
        'four applications must supply distinct private evidence values to exact scored results elsewhere',
        'require two to four native persistent effects and at least three scalar changes',
        'each participating application needs native assertion coverage',
        'expose all necessary reads and writes through the official native interaction surface supported by the runtime',
        'changing either while holding the other evidence fixed must alter a selected object, allowed action, derived value or required effect',
        'require final observable results, not read order, routes, intermediate states, private history or hidden formatting',
    ]
    if not all(x in normalized for x in required):
        raise ValueError('Marketing five-app profile requires the complete observed obligation bundle')
    clause=re.search(r'select a campaign application (.+?)\. use a consent',normalized)
    groups=[re.findall(r'`([a-z0-9_]+)`',g) for g in re.findall(r'\(([^)]+)\)',clause.group(1))] if clause else []
    expected=[['mailchimp','buffer','ads_app'],['google_drive','docusign'],
        ['calendly','google_calendar'],['google_sheets','airtable'],['asana','monday','jira','gmail','slack']]
    if groups!=expected or profile.get('application_count')!=5:
        raise ValueError('Marketing five-app application groups changed')
    return dict(application_groups_exactly_one=groups,public_request_char_max=1499,
        strict_minimum_private_evidence_sources=4,strict_named_gate_causal_services=True,
        strict_cross_app_evidence_dataflow=True,strict_unique_private_evidence_values=True,
        strict_native_evidence_readability=True,strict_minimum_meaningful_state_changes=3,
        strict_final_state_observability=True,strict_minimum_native_join_pairs=3,
        strict_native_join_service_count=5,strict_opposite_policy_fixture=True,
        strict_minimum_policy_fixtures=2,strict_marketing_fiveapp_policy_conditions=True,
        marketing_fiveapp_contract=CONTRACT)
