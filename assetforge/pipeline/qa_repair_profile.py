"""Source-bound cold repair profiles; never infer inheritance from revision names."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = 'root-author-execution-profile-preserved-on-repair-v1'
ENV = 'QA18K_REPAIR_INHERIT_SOURCE_PROFILE'
PROFILE_FLAGS = (
    'QA18K_THREEAPP_NATIVE_READ_PROFILE',
    'QA18K_FOURAPP_R54_PROFILE',
    'QA18K_RARE_TWOAPP_CAUSAL_PROFILE', 'QA18K_SINGLEAPP_THREEFACT_PROFILE',
    'QA18K_MARKETING_THREEFACT_PROFILE', 'QA18K_MARKETING_COORDINATED_STATUS_PROFILE',
    'QA18K_SALES_THREEFACT_PROFILE',
    'QA18K_FIVEAPP_DEPENDENCY_PROFILE',
    'QA18K_NATIVE_JOIN_BRIDGE_PROFILE',
    'QA18K_HR_FIVEAPP_PROFILE',
    'QA18K_MARKETING_FIVEAPP_PROFILE',
    'QA18K_SALES_FIVEAPP_PROFILE',
    'QA18K_FIVEAPP_OUTCOME_SOURCE_PROFILE',
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bound_source_profile(task_path, rubric_path, *, root=ROOT):
    root = Path(root).resolve()
    task_path = Path(task_path).resolve()
    rubric_path = Path(rubric_path).resolve()
    task_path.relative_to(root / 'assetforge/runs')
    lineage = []
    # Repair revisions intentionally retain the same root task_id.  A task_id
    # repeat therefore is not a cycle by itself; detect an actual ancestry
    # cycle from the immutable path/content identity instead.
    seen = set()
    expected_root = None
    for depth in range(3):
        raw = task_path.read_bytes()
        task = json.loads(raw)
        tid = task['task_id']
        identity = (str(task_path), sha(task_path))
        if identity in seen:
            raise ValueError('repair source profile ancestry cycle')
        seen.add(identity)
        lineage.append(dict(path=str(task_path.relative_to(root)), sha256=sha(task_path), task_id=tid))
        parent = task.get('generation_provenance', {}).get('qa_repair_lineage')
        if not parent:
            break
        if depth == 2 or (expected_root is not None and expected_root != parent['root_task_id']):
            raise ValueError('repair source profile ancestry bound')
        expected_root = parent['root_task_id']
        task_path = (root / parent['parent_task_path']).resolve()
        task_path.relative_to(root / 'assetforge/runs')
        if sha(task_path) != parent['parent_task_sha256']:
            raise ValueError('repair source profile parent hash drift')
    if expected_root is not None and task['task_id'] != expected_root:
        raise ValueError('repair source profile root identity drift')
    preflight = task_path.parents[2] / 'preflight.json'
    if not preflight.is_file():
        raise ValueError('original source profile preflight unavailable')
    pre = json.loads(preflight.read_text())
    entry = pre['rubrics'][task['domain_label']]
    if (entry['relative_path'] != str(rubric_path.relative_to(root))
            or entry['sha256'] != sha(rubric_path)):
        raise ValueError('original source profile Rubric identity drift')
    profile = entry['mechanical_profile']
    if not isinstance(profile, dict) or not profile:
        raise ValueError('original source execution profile missing')
    return dict(contract=CONTRACT, ancestry=lineage,
                original_preflight=str(preflight.relative_to(root)),
                original_preflight_sha256=sha(preflight), mechanical_profile=profile)


def profile_environment(profile):
    flags = {}
    if profile.get('three_app_native_read_contract'):
        from .three_app_native_read_profile import ENV, validate_profile
        validate_profile(profile)
        flags[ENV] = '1'
    if profile.get('strict_sales_fiveapp_policy_conditions'):
        from .five_app_outcome_sources import validate_profile
        validate_profile(profile)
        flags['QA18K_SALES_FIVEAPP_PROFILE'] = '1'
    if profile.get('four_app_r54_contract'):
        from .four_app_r54_profile import ENV, validate_profile
        validate_profile(profile)
        flags[ENV] = '1'
    if profile.get('strict_marketing_fiveapp_policy_conditions'):
        if profile.get('application_count') != 5 or profile.get('strict_minimum_private_evidence_sources') != 4:
            raise ValueError('source Marketing five-app profile lacks the complete causal gate')
        flags['QA18K_MARKETING_FIVEAPP_PROFILE'] = '1'
    if profile.get('strict_hr_fiveapp_policy_conditions'):
        if profile.get('application_count') != 5 or profile.get('strict_minimum_private_evidence_sources') != 4:
            raise ValueError('source HR five-app profile lacks the complete causal gate')
        flags['QA18K_HR_FIVEAPP_PROFILE'] = '1'
    if profile.get('strict_independent_readable_policy_facts'):
        apps = set(profile.get('permitted_applications', []))
        if apps == {'google_sheets', 'google_calendar', 'docusign'}:
            flags['QA18K_SINGLEAPP_THREEFACT_PROFILE'] = '1'
        elif apps == {'mailchimp', 'buffer', 'ads_app'}:
            flags['QA18K_MARKETING_THREEFACT_PROFILE'] = '1'
            if profile.get('strict_marketing_coordinated_status'):
                flags['QA18K_MARKETING_COORDINATED_STATUS_PROFILE'] = '1'
        elif apps == {'hubspot', 'salesforce'}:
            from .single_app_policy_facts import SALES_ENV, validate_sales_profile
            validate_sales_profile(profile)
            flags[SALES_ENV] = '1'
        else:
            raise ValueError('unknown source single-app fact profile')
    if (not profile.get('construction_application_roles') and
            profile.get('application_count') == 2 and profile.get('strict_named_gate_causal_services')):
        flags['QA18K_RARE_TWOAPP_CAUSAL_PROFILE'] = '1'
    if profile.get('strict_five_app_native_dependencies'):
        flags['QA18K_FIVEAPP_DEPENDENCY_PROFILE'] = '1'
    if profile.get('strict_native_join_bridges'):
        if not (profile.get('strict_five_app_native_dependencies')
                or profile.get('strict_hr_fiveapp_policy_conditions')
                or profile.get('strict_marketing_fiveapp_policy_conditions')
                or profile.get('strict_sales_fiveapp_policy_conditions')):
            raise ValueError('source native join bridge profile lacks five-app dependency gate')
        flags['QA18K_NATIVE_JOIN_BRIDGE_PROFILE'] = '1'
    if profile.get('strict_fiveapp_output_source_selection'):
        from .five_app_outcome_sources import validate_profile, ENV
        validate_profile(profile)
        flags[ENV] = '1'
    return flags


def require_source_profile(current, source):
    lost = [key for key, value in source.items() if current.get(key) != value]
    if lost:
        raise ValueError('repair lost original execution profile: ' + ', '.join(sorted(lost)))


def group_environment(rows, environment, *, root=ROOT):
    root = Path(root).resolve()
    choices = []
    for row in rows:
        review = json.loads((root / row['source_review']).read_text())
        ref = review['packet']['source_binding']['generated_task']
        path = (root / ref['path']).resolve()
        if sha(path) != ref['sha256'] or ref['task_id'] != row['source_task_id']:
            raise ValueError('repair group source profile task drift')
        proof = bound_source_profile(path, root / row['rubric'], root=root)
        choices.append(profile_environment(proof['mechanical_profile']))
    if not choices or any(choice != choices[0] for choice in choices):
        raise ValueError('repair group has mixed source profile environments')
    result = {k: v for k, v in environment.items() if k not in PROFILE_FLAGS}
    result.update(choices[0])
    result[ENV] = '1'
    return result
