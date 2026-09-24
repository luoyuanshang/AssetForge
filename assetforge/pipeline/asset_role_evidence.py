"""Consume role-specific native evidence, independently of aggregate pass flags.

This is an additional admission check. It never grants semantic review or QA release.
"""
from .construction_assets import require, digest
from .construction_background_native import validate_evidence


def required_case_ids(example):
    aid, adapter = example['asset_id'], example['adapter']
    construction = example['construction']
    required = {'correct', 'no_action', 'wrong_result'}
    if any(e.get('instance_role') == 'target_effect' for e in construction['entities'].values()):
        required |= {'wrong_target', 'extra_non_target_write'}
    if aid in ('approval_decision_state', 'queue_handoff_state'):
        required |= {'missing_state_effect', 'missing_audit_effect'}
    if adapter in ('zoom', 'xero', 'xero_contacts', 'quickbooks', 'quickbooks_customers') and (
            aid == 'native_field_state' or aid.startswith('app_')):
        required.add('protected_field_corruption')
    if adapter in ('zendesk', 'freshdesk', 'intercom', 'zoho_desk', 'gorgias') and (
            aid in ('native_append_effect', 'approval_decision_state', 'queue_handoff_state') or aid.startswith('app_')):
        required.add('protected_field_corruption')
    if aid == 'audit_archive_state': required.add('protected_source_status')
    if aid == 'reconciliation_adjustment': required.add('protected_source_field')
    return required


def validate_role_evidence(example, native, protocol_ref):
    require(native.get('runtime_protocol') == protocol_ref, 'asset case runtime protocol mismatch')
    require(native.get('example_sha256') == digest(example), 'asset role evidence input mismatch')
    rows = native.get('cases', [])
    cases = {row['case_id']: row for row in rows}
    require(len(cases) == len(rows), 'duplicate native case identity')
    require(required_case_ids(example) <= set(cases), 'missing required role/protection native case')
    for cid in required_case_ids(example):
        row = cases[cid]
        expected = cid == 'correct'
        require(row.get('expected_strict') is expected and row.get('observed_strict') is expected,
                'asset role boundary did not discriminate: ' + cid)
        if cid != 'no_action':
            require(bool(row.get('successful_native_calls')), 'role boundary did not call the native API')
        require(row.get('score', {}).get('strict_pass') is expected,
                'asset role result disagrees with native scorer')
    construction = example['construction']
    background = [o for o in construction['obligations'] if o.get('kind') == 'structural_background']
    if background:
        validate_evidence(native.get('background_native_evidence'), construction, example['source'])
    if (example['adapter']=='linkedin' and example['version']=='1.2.0' and
            example['asset_id'] in ('app_linkedin','native_create_effect')):
        rejected=native.get('rejected_parameters',[])
        require({r.get('visibility') for r in rejected} == {'CONNECTIONS','connections-only','anyone','private',None}
                and len(rejected)==5 and all(r.get('rejected_before_native_call') is True for r in rejected),
                'LinkedIn unsupported-visibility boundary evidence missing')
    return {'required_cases': sorted(required_case_ids(example)),
            'structural_background_obligations': len(background), 'passed': True}
