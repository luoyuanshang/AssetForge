"""Compact Author-owned native cases; no synthesized task meaning or scorer changes.

Reference references avoid duplicating long action prefixes. Each case is independently
reset and scored by the pinned runtime. Semantic category/coverage truth remains an
Reviewer duty, not something an action hash proves.
"""
from collections import Counter
import copy
import json
import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from .runtime_value_normalise import normalize_runtime_value

CONTRACT = 'author-owned-native-cases-with-proven-identity-and-public-basis-reference-v4'
PUBLIC_BASIS_CONTRACT = 'exact-current-public-request-reference-v1'
WORKSHEET_PARENT_CONTRACT = 'identity-bound-scored-cell-native-parent-deletion-and-replacement-v1'
CORE_CATEGORIES = ('wrong_evidence', 'wrong_join', 'wrong_target', 'effect_omission',
                   'protected_field_corruption', 'equivalent_valid_path')
EXPECTED = {**{k: False for k in CORE_CATEGORIES if k != 'equivalent_valid_path'},
            'equivalent_valid_path': True, 'restoration': True, 'idempotent_write': True,
            'missing_member': False, 'extra_member': False, 'wrong_policy_result': False,
            'identity_substitution': False, 'forbidden_action': False,
            'wrong_exact_text': False, 'equivalent_text': True,
            'split_object_properties': False, 'wrong_boundary_result': False,
            'valid_boundary_result': True}


def public_basis_schema(description):
    return {'description': description + ' You may use {"public_request": true} to reference '
        'the exact current public request without copying it. This is only an evidence reference, '
        'not proof that a case faithfully tests that obligation.',
        'anyOf': [{'type': 'string'}, {'type': 'object', 'additionalProperties': False,
            'properties': {'public_request': {'type': 'boolean', 'const': True}},
            'required': ['public_request']}]}


def resolve_public_basis(value, instruction, *, label='actual public obligation'):
    if isinstance(value, dict) and set(value) == {'public_request'} and value['public_request'] is True:
        value = instruction
    if (not isinstance(value, str) or not isinstance(instruction, str)
            or len(value.strip()) < 8 or value not in instruction):
        raise ValueError(f'must quote the {label} or use the exact public-request reference')
    return value


def schema(required_categories=(), *, require_worksheet_parent=False):
    action = {'type': 'object', 'additionalProperties': False,
              'properties': {'method': {'type': 'string'}, 'url': {'type': 'string'},
                             'params': {}, 'body': {}}, 'required': ['method', 'url']}
    return {'type': 'array', 'minItems': max(1, len(required_categories)), 'maxItems': 64, 'description': (
        'Private executable native cases, not solver instructions. For each material '
        'counterexample or alternative valid path, quote the exact public obligation, '
        'bind the relevant zero-based assertion indices, and supply native calls. '
        'An action may be {"reference_index":N} to reuse that base reference path call exactly. '
        'Start independently from initial or reference_complete; assertions stay unchanged. '
        'Do not force a negative source edit when the public request does not protect '
        'the source. Wrong evidence/join must yield a wrong business result, not merely '
        'omit a read. All calls must execute successfully; provider/runtime errors are '
        'not valid negative cases. Repeated labels cannot replace distinct coverage. '
        'Include every applicable obligation from the Author Rubric, not just one '
        'representative per category. A category label does not establish semantic coverage. '
        'Equivalent identifiers are tested only after native identity resolution proves the same '
        'employee. An action-record ID, employee number or email is not automatically a native '
        'alias; success for an arbitrary target string is not proof of a same-object mutation. '
        + (' Scored row-cell parents must preserve their original worksheet identity: native '
           'deletion and same-title replacement are tested. Use stable native identity witnesses; '
           'orphaned internal row values do not establish worksheet preservation.'
           if require_worksheet_parent else '')
        + (' Required categories: ' + ', '.join(required_categories) + '.' if required_categories else '')),
        'items': {'type': 'object', 'additionalProperties': False, 'properties': {
            'case_id': {'type': 'string'}, 'category': {'type': 'string', 'enum': sorted(EXPECTED)},
            'public_basis': public_basis_schema('Exact quote of the public obligation tested by this case.'),
            'covered_assertion_indices': {'type': 'array', 'minItems': 1, 'uniqueItems': True,
                                         'items': {'type': 'integer', 'minimum': 0}},
            'start_state': {'type': 'string', 'enum': ['initial', 'reference_complete']},
            'actions': {'type': 'array', 'minItems': 1, 'maxItems': 64, 'items': {'anyOf': [
                action, {'type': 'object', 'properties': {'reference_index': {'type': 'integer', 'minimum': 0}},
                         'required': ['reference_index'], 'additionalProperties': False}]}}},
            'required': ['case_id', 'category', 'public_basis', 'covered_assertion_indices',
                         'start_state', 'actions']}}


def _forbidden_employee_alias_programs(initial_state, actions, assertions, failed_indices):
    """Narrow pinned-native alias expansion, never infer a new public prohibition.

    Called only for an Author-supplied forbidden_action case that already fails.
    Only swap the target of a supported BambooHR employee POST, not arbitrary
    equal strings, another employee, subresource, field, or source-state value.
    """
    from . import official_task_package as p
    records = ((initial_state.get('bamboohr') or {}).get('actions') or {}).get('employee') or []
    official = p._official_imports()
    identity_world = official['WorldState'](**normalize_runtime_value(copy.deepcopy(initial_state)))
    identity_world.meta.allowed_services = ['bamboohr']

    def resolve(identity):
        # The pinned GET uses find_actions(employee_id), not action-record id.
        # Missing filter keys are wildcards in find_actions: they cannot prove
        # identity either. Match the actual native read and a single keyed row.
        matches = identity_world.bamboohr.find_actions('employee', {'employee_id': identity})
        if len(matches) != 1 or not matches[0].params.get('employee_id'):
            return None
        actual = json.loads(official['api_fetch'](
            identity_world, 'GET', 'bamboohr/v1/employees/' + quote(identity, safe='')))
        expected = matches[0].to_result_dict()
        return expected if actual == expected else None

    seen = set()
    for i, action in enumerate(actions):
        if str(action.get('method', '')).upper() != 'POST':
            continue
        parts = urlsplit(action.get('url', ''))
        match = re.search(r'/v1/employees/([^/]+)$', parts.path)
        if not match or p._reference_action_target_service(action) != 'bamboohr':
            continue
        target = unquote(match.group(1))
        if not any(assertions[j].get('type') == 'bamboohr_action_not_exists'
                   and assertions[j].get('action_key') == 'update_employee'
                   and (assertions[j].get('params') or {}).get('employee_id') == target
                   for j in failed_indices):
            continue  # No same-target explicit event prohibition has been proved.
        for record in records:
            aliases = {record.get('id'), (record.get('params') or {}).get('employee_id')}
            aliases = {a for a in aliases if isinstance(a, str) and a.strip()}
            if target not in aliases or len(aliases) != 2:
                continue
            for alias in sorted(aliases - {target}):
                resolved_target = resolve(target)
                if resolved_target is None or resolve(alias) != resolved_target:
                    continue  # Do not invent a same-object ban from shared JSON nesting.
                changed = copy.deepcopy(actions)
                path = parts.path[:match.start(1)] + quote(alias, safe='')
                changed[i]['url'] = urlunsplit(parts._replace(path=path))
                fingerprint = p._sha(changed)
                if fingerprint not in seen:
                    seen.add(fingerprint)
                    yield changed, target, alias


def run_worksheet_parent_cases(*, initial_state, assertions, reference_world, allowed_services):
    """Check only parents of exact native scored row-cell witnesses.

    Invoked when the frozen Rubric explicitly requires original parent identity.
    No assertions, tasks or public obligations are synthesized. Other container
    types and other assertion families still require independent semantic review.
    """
    from . import official_task_package as p
    parents = {}
    for index, assertion in enumerate(assertions):
        if assertion.get('type') != 'google_sheets_row_cell_equals':
            continue
        spreadsheet = assertion.get('spreadsheet_id')
        worksheet = assertion.get('worksheet_id') or assertion.get('worksheet') or assertion.get('worksheet_name')
        row_id = assertion.get('row_id')
        if worksheet:
            row = reference_world.google_sheets.get_row_by_id(spreadsheet, worksheet, row_id)
            rows = [row] if row is not None else []
        else:
            rows = [row for row in reference_world.google_sheets.rows
                    if row.spreadsheet_id == spreadsheet and row.row_id == row_id]
        if len(rows) != 1:
            raise ValueError(f'worksheet parent: missing or ambiguous scored row witness at assertion {index}')
        row = rows[0]
        parent = reference_world.google_sheets.get_worksheet_by_id(row.spreadsheet_id, row.worksheet_id)
        if parent is None:
            raise ValueError(f'worksheet parent: scored row at assertion {index} is already orphaned')
        parents.setdefault((row.spreadsheet_id, parent.id), {'title': parent.title, 'indices': []})['indices'].append(index)
    official = p._official_imports()
    results, failures = [], []
    for (spreadsheet, worksheet), spec in parents.items():
        delete = {'method': 'POST', 'url': 'https://sheets.googleapis.com/v4/spreadsheets/' + quote(spreadsheet, safe='') + ':batchUpdate',
                  'body': {'requests': [{'deleteSheet': {'sheetId': worksheet}}]}}
        replacement = {'method': 'POST', 'url': delete['url'], 'body': {'requests': [
            {'addSheet': {'properties': {'title': spec['title']}}}]}}
        for label, actions in [('delete_parent', [delete]), ('same_title_replacement', [delete, replacement])]:
            world = copy.deepcopy(reference_world)
            world.meta.allowed_services = list(allowed_services)
            receipts, _ = p._execute_official_action_sequence(
                official=official, world=world, actions=actions, label='worksheet parent ' + label)
            if world.google_sheets.get_worksheet_by_id(spreadsheet, worksheet) is not None:
                raise ValueError('worksheet parent: native control did not remove the original identity')
            score = p._official_score(initial_state=initial_state, assertions=assertions, world=world)
            result = {'case': label, 'spreadsheet_id': spreadsheet, 'worksheet_id': worksheet,
                      'scored_row_assertion_indices': spec['indices'], 'observed_strict': score['strict_pass'],
                      'native_call_count': len(receipts), 'program_sha256': p._sha(actions),
                      'terminal_state_sha256': p._sha(world.model_dump(mode='json'))}
            results.append(result)
            if score['strict_pass']:
                failures.append(result)
    if failures:
        raise ValueError('worksheet parent identity is not preserved by the hidden native assertions; '
                         'bind the required original worksheet identity (not only its title), and test deletion/replacement. '
                         + json.dumps({'failed_cases': failures}, ensure_ascii=False))
    return results


def run_cases(*, initial_state, assertions, reference_actions, reference_world, cases,
              allowed_services, instruction, required_categories=()):
    from . import official_task_package as p
    if not isinstance(cases, list) or not 1 <= len(cases) <= 64:
        raise ValueError('native_construction_cases must contain 1-64 executable cases')
    official = p._official_imports()
    WorldState = official['WorldState']
    seen_ids = set(); seen_programs = set(); counts = Counter(); results = []; alias_results = []
    for index, case in enumerate(cases):
        label = f'native_construction_cases[{index}]'
        keys = {'case_id', 'category', 'public_basis', 'covered_assertion_indices', 'start_state', 'actions'}
        if not isinstance(case, dict) or set(case) != keys:
            raise ValueError(f'{label} must contain exactly {sorted(keys)}')
        cid, category = case['case_id'], case['category']
        if not isinstance(cid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', cid) or cid in seen_ids:
            raise ValueError(f'{label} needs a unique bounded case_id')
        if category not in EXPECTED:
            raise ValueError(f'{label} unsupported semantic category')
        try:
            basis = resolve_public_basis(case['public_basis'], instruction)
        except ValueError as exc:
            raise ValueError(f'{label} {exc}') from exc
        indices = case['covered_assertion_indices']
        if (not isinstance(indices, list) or not indices or any(type(i) is not int or
                not 0 <= i < len(assertions) for i in indices) or len(set(indices)) != len(indices)):
            raise ValueError(f'{label} invalid covered_assertion_indices')
        start = case['start_state']
        if start not in ('initial', 'reference_complete'):
            raise ValueError(f'{label} invalid reset boundary')
        raw = case['actions']
        if not isinstance(raw, list) or not 1 <= len(raw) <= 64:
            raise ValueError(f'{label} actions must contain 1-64 calls or reference path references')
        actions = []
        for row in raw:
            if isinstance(row, dict) and set(row) == {'reference_index'}:
                n = row['reference_index']
                if type(n) is not int or not 0 <= n < len(reference_actions):
                    raise ValueError(f'{label} reference_index out of range')
                actions.append(copy.deepcopy(reference_actions[n]))
            elif (isinstance(row, dict) and {'method', 'url'} <= set(row) <= {'method', 'url', 'params', 'body'}):
                actions.append(copy.deepcopy(row))
            else:
                raise ValueError(f'{label} invalid native action or reference path reference')
        program = p._sha({'start_state': start, 'actions': actions})
        if program in seen_programs:
            raise ValueError(f'{label} duplicates an existing concrete native case')
        if category == 'equivalent_valid_path' and start == 'initial' and actions == reference_actions:
            raise ValueError(f'{label} repeats the base reference path rather than an alternative path')
        world = copy.deepcopy(reference_world) if start == 'reference_complete' else WorldState(**normalize_runtime_value(copy.deepcopy(initial_state)))
        world.meta.allowed_services = list(allowed_services)
        receipts, mutations = p._execute_official_action_sequence(
            official=official, world=world, actions=actions, label=label)
        score = p._official_score(initial_state=initial_state, assertions=assertions, world=world)
        failed = [i for i, r in enumerate(score['assertion_results'])
                  if not r.get('excluded', False) and not r.get('passed')]
        expected = EXPECTED[category]
        if score['strict_pass'] is not expected or not expected and (not failed or not set(failed) <= set(indices)):
            raise ValueError(f'{label} expected strict={expected}, observed strict={score["strict_pass"]}; '
                             f'failed scored assertion indices={failed}; preserve unrelated obligations')
        if category == 'forbidden_action':
            for variant, source_identity, alias in _forbidden_employee_alias_programs(initial_state, actions, assertions, failed):
                alias_world = copy.deepcopy(reference_world) if start == 'reference_complete' else WorldState(**normalize_runtime_value(copy.deepcopy(initial_state)))
                alias_world.meta.allowed_services = list(allowed_services)
                alias_receipts, _ = p._execute_official_action_sequence(
                    official=official, world=alias_world, actions=variant,
                    label=f'{label} native identity alias')
                alias_score = p._official_score(initial_state=initial_state, assertions=assertions, world=alias_world)
                alias_failed = [i for i, r in enumerate(alias_score['assertion_results'])
                    if not r.get('excluded', False) and not r.get('passed')]
                caught_forbidden_alias = any(
                    assertions[j].get('type') == 'bamboohr_action_not_exists'
                    and assertions[j].get('action_key') == 'update_employee'
                    and (assertions[j].get('params') or {}).get('employee_id') in (None, alias)
                    for j in alias_failed)
                if alias_score['strict_pass'] is not False or not caught_forbidden_alias:
                    raise ValueError(f'{label} native identity alias {source_identity!r} -> {alias!r} '
                        'bypasses the Author-declared forbidden employee update; '
                        'bind its complete native identity family in hidden assertions and construction cases')
                alias_results.append({'source_case_id': cid, 'public_basis': basis,
                    'source_identity': source_identity, 'alias_identity': alias,
                    'observed_strict': False, 'native_call_count': len(alias_receipts),
                    'failed_assertion_indices': alias_failed,
                    'resolved_program_sha256': p._sha(variant),
                    'terminal_state_sha256': p._sha(alias_world.model_dump(mode='json'))})
        counts[category] += 1; seen_ids.add(cid); seen_programs.add(program)
        results.append({'case_id': cid, 'category': category, 'public_basis': basis,
            'covered_assertion_indices': indices, 'start_state': start, 'expected_strict': expected,
            'observed_strict': score['strict_pass'], 'partial_credit': score['partial_credit'],
            'failed_assertion_indices': failed, 'native_call_count': len(receipts),
            'state_changing_call_count': mutations, 'case_sha256': p._sha(case),
            'resolved_program_sha256': program, 'terminal_state_sha256': p._sha(world.model_dump(mode='json'))})
    missing = sorted(set(required_categories) - set(counts))
    if missing:
        raise ValueError(f'native_construction_cases missing required categories: {missing}')
    return {'contract': CONTRACT, 'passed': True, 'case_count': len(results),
            'public_basis_reference_contract': PUBLIC_BASIS_CONTRACT,
            'category_counts': dict(counts), 'cases': results,
            'derived_alias_case_count': len(alias_results), 'derived_alias_cases': alias_results,
            'official_scorer_modified': False, 'solver_visible': False,
            'semantic_coverage_requires_independent_review': True,
            'exhaustive_semantic_coverage_proved': False}
