"""Self-authored functional examples, never automatically admitted dataset tasks.

Two business contexts exercise the same fragments and different native adapters.
Their complete inputs are intentionally public to asset validation and review.
"""
import copy
from .construction_assets import SCHEMA, construct, digest


def blueprint(context, root_id, seed):
    hr = context == 'hr_training'
    if context not in ('hr_training', 'renewal'):
        raise ValueError('unknown authored functional context')
    source = []; target = []
    for i, entity in enumerate(('cedar', 'birch', 'elm')):
        key = f'{entity}.{seed}@example.org'
        if hr:
            source_fields = {'firstName': 'Morgan', 'lastName': 'Vale', 'department': ['Operations', 'Finance', 'Legal'][i],
                             'employmentClass': 'Regular', 'trainingClearance': 'Approved'}
            target_fields = {'name': 'Morgan Vale', 'status_text': 'Available', 'status_emoji': 'seedling'}
        else:
            source_fields = {'first_name': 'Morgan', 'last_name': 'Vale', 'department': ['Enterprise', 'Retail', 'Partner'][i],
                             'nda_status': 'Signed'}
            target_fields = {'firstname': 'Morgan', 'lastname': 'Vale', 'jobtitle': 'Account contact', 'phone': '+1-202-555-0101'}
        source.append({'entity': entity, 'business_key': key, 'fields': source_fields})
        target.append({'entity': entity, 'business_key': key, 'fields': target_fields})
    return {'schema_version': SCHEMA, 'root_task_id': root_id, 'seed': seed, 'business_time': '2026-08-01T09:00:00+00:00',
        'assets': [
            {'id': 'customer_link', 'version': '1.0.1' if hr else '1.2.0', 'alias': 'join',
             'reason': 'Exact directory-to-destination identity despite duplicate display names.',
             'parameters': {'business_context': context, 'match_semantics': 'exact_email_unique',
                'source': {'adapter': 'bamboohr_employees' if hr else 'salesforce_contacts', 'records': source},
                'target': {'adapter': 'slack_users' if hr else 'hubspot_contacts', 'records': target}}},
            {'id': 'readable_policy_exception', 'version': '1.1.0', 'alias': 'policy',
             'reason': 'A discoverable business policy selects the normal or exception outcome.',
             'parameters': {'business_context': context, 'readable_carrier': 'slack_topic',
                'channel_name': 'training-rules' if hr else 'renewal-rules',
                'title': 'Training readiness' if hr else 'Enterprise renewal review',
                'scope': 'BambooHR employees whose department is Operations.' if hr else 'Salesforce contacts whose department is Enterprise.',
                'rule': 'For Approved trainingClearance set status text to Training seat ready.' if hr else 'For Signed nda_status set HubSpot jobtitle to Renewal reviewed.',
                'exception': 'If trainingClearance is Pending instead set status text to Training clearance pending.' if hr else 'If nda_status is Pending instead set HubSpot jobtitle to Legal follow-up.',
                'precedence': 'exception_over_rule', 'protected': True}},
            {'id': 'bounded_contact_batch', 'version': '1.0.1', 'alias': 'batch',
             'reason': 'Apply the policy to the exactly linked in-scope contact and preserve the declared field.',
             'parameters': {'business_context': context, 'entity_refs': ['join.target.cedar'],
                'updates': {'status_text': 'Training seat ready'} if hr else {'jobtitle': 'Renewal reviewed'},
                'protected_fields': ['status_emoji'] if hr else ['phone'],
                'public_scope': 'Only counterparts of source records in the policy department; preserve the other counterpart values.'}},
            # Second readable-policy carrier: the same policy text published as a Gmail message body.
            # Gmail is the most scored application in the pinned the frozen release distribution (65.4%) and 1.1.0
            # is the version that first makes it reachable from the asset library.
            {'id': 'readable_policy_exception', 'version': '1.1.0', 'alias': 'policy_mail',
             'reason': 'The same policy is also discoverable from a Gmail message body.',
             'parameters': {'business_context': context, 'readable_carrier': 'gmail_message_body',
                'sender': 'policy@{seed}.example.org'.format(seed=seed), 'recipient': 'desk@{seed}.example.org'.format(seed=seed),
                'subject': 'Training rules' if hr else 'Renewal review rules',
                'title': 'Training readiness' if hr else 'Enterprise renewal review',
                'scope': 'BambooHR employees whose department is Operations.' if hr else 'Salesforce contacts whose department is Enterprise.',
                'rule': 'For Approved trainingClearance set status text to Training seat ready.' if hr else 'For Signed nda_status set HubSpot jobtitle to Renewal reviewed.',
                'exception': 'If trainingClearance is Pending instead set status text to Training clearance pending.' if hr else 'If nda_status is Pending instead set HubSpot jobtitle to Legal follow-up.',
                'precedence': 'exception_over_rule', 'protected': True}},
            # Google Sheets carrier: the second most scored application (30.2%) with no admitted
            # carrier before 1.0.0 of sheet_row_state.
            {'id': 'sheet_row_state', 'version': '1.0.0', 'alias': 'ledger',
             'reason': 'Record the accepted renewal outcome on the review ledger row.',
             'parameters': {'business_context': context,
                'spreadsheet_title': 'Training register' if hr else 'Renewal review ledger',
                'worksheet_title': 'Rows' if hr else 'Ledger',
                'headers': ['row_key', 'owner_email', 'review_state', 'locked_note'],
                'row_key': 'row-cedar',
                'cells': {'owner_email': 'cedar.{seed}@example.org'.format(seed=seed), 'review_state': 'Ready'},
                'protected_fields': ['locked_note'], 'protected_values': {'locked_note': 'seeded-lock'}}}
        ]}


def full_example(context, root_id, seed, catalog):
    bp = blueprint(context, root_id, seed); c = construct(bp, catalog); hr = context == 'hr_training'
    instruction = (
        'Follow #training-rules for the BambooHR Operations employees and their Slack counterparts. '
        'Match by the exact complete work email, never display name. Set their Slack status text according to the rule or priority exception. '
        'The BambooHR directory is read-only: do not submit employee updates. Keep the listed employees\' original directory entries, all status emojis, the status text of other listed counterparts and the policy topic unchanged.'
        ' The same policy is also published in the Gmail message body and must stay readable and unmodified.'
        ' Finally record the accepted outcome for row-cedar on the "Training register" ledger: set owner_email and review_state, and leave the protected locked_note cell untouched.'
        if hr else
        'Follow #renewal-rules for Salesforce Enterprise contacts and their HubSpot counterparts. '
        'Match by the exact complete email, never display name. Set their HubSpot job title according to the rule or priority exception. '
        'Keep the listed Salesforce contacts\' email, department and NDA status, all HubSpot phone numbers, the job titles of other listed counterparts and the policy topic unchanged.'
        ' The same policy is also published in the Gmail message body and must stay readable and unmodified.'
        ' Finally record the accepted outcome for row-cedar on the "Renewal review ledger": set owner_email and review_state, and leave the protected locked_note cell untouched.'
    )
    assertions = copy.deepcopy(c['assertions'])
    target = c['entities']['join.target.cedar']; other = c['entities']['join.target.birch']
    for entity in ('birch', 'elm'):
        r = c['entities']['join.target.' + entity]
        if hr:
            assertions.append({'type': 'slack_user_status_equals', 'user': r['id'], 'status_text': 'Available', 'status_emoji': 'seedling'})
        else:
            assertions.extend([{'type': 'hubspot_contact_has_property', 'contact_id': r['id'], 'property': 'jobtitle', 'value': 'Account contact'},
                               {'type': 'hubspot_contact_has_property', 'contact_id': r['id'], 'property': 'phone', 'value': '+1-202-555-0101'}])
    source_assertions=[]
    for entity in ('cedar','birch','elm'):
        r=c['entities']['join.source.'+entity]
        if hr:
            source_assertions.append(len(assertions))
            assertions.append({'type':'bamboohr_action_exists','action_key':'employee','params':copy.deepcopy(r['record']['params'])})
        else:
            for field in ('email','department','nda_status'):
                source_assertions.append(len(assertions))
                assertions.append({'type':'salesforce_contact_field_equals','contact_id':r['id'],'field':field,'value':r['record'][field]})
    if hr:
        source_assertions.append(len(assertions))
        assertions.append({'type':'bamboohr_action_not_exists','action_key':'update_employee','params':{}})
    effect=[i for i,a in enumerate(assertions) if (a.get('user')==target['id'] and a.get('status_text')=='Training seat ready') or
            (a.get('contact_id')==target['id'] and a.get('property')=='jobtitle')]
    non_target=[i for i,a in enumerate(assertions) if a.get('user')==other['id'] or a.get('contact_id')==other['id']]
    actions = copy.deepcopy(c['reads'] + c['actions'])
    wrong_target = copy.deepcopy(c['actions'][0])
    if hr:
        wrong_target['body']['user'] = other['id']
    else:
        wrong_target['url'] = 'hubspot/crm/v3/objects/contacts/' + other['id']
    wrong_value = copy.deepcopy(c['actions'][0])
    field = 'status_text' if hr else 'jobtitle'; alt_value = 'Training clearance pending' if hr else 'Legal follow-up'
    wrong_value['body']['profile' if hr else 'properties'][field] = alt_value
    corrupt = copy.deepcopy(c['actions'][0])
    if hr:
        corrupt['body']['profile']['status_emoji'] = 'warning'
    else:
        corrupt['body']['properties'] = {'phone': '+1-202-555-0199'}
    def case(cid, category, calls, start='initial', indices=None):
        return {'case_id': cid, 'category': category, 'public_basis': {'public_request': True},
                'covered_assertion_indices': indices or list(range(len(assertions))), 'start_state': start, 'actions': calls}
    policy_corrupt={'method':'POST','url':'slack/conversations.setTopic',
                    'body':{'channel':c['entities']['policy.policy']['id'],'topic':'Unapproved policy replacement'}}
    source_target=c['entities']['join.source.cedar']
    source_corrupt=({'method':'POST','url':'bamboohr/v1/employees/'+source_target['id'],'body':{'department':'Unauthorized change'}} if hr else
        {'method':'PATCH','url':'https://example.invalid/services/data/v1/sobjects/Contact/'+source_target['id'],
         'body':{'Department':'Unauthorized change'}})
    # Google Sheets carrier: the written cells start at the exported placeholder, so an omitted or
    # wrong write must fail while the protected sibling cell must stay untouched.
    ledger = c['entities']['ledger.row']
    ledger_row_id = ledger['record']['row_id']
    ledger_indices = [i for i, a in enumerate(assertions) if a.get('row_id') == ledger_row_id]
    ledger_scored = [i for i in ledger_indices if assertions[i].get('column') == 'review_state']
    ledger_protected = [i for i in ledger_indices if assertions[i].get('column') == 'locked_note']
    ledger_action = next(a for a in c['actions'] if a.get('url', '').startswith('sheets/'))
    sheet_wrong_value = copy.deepcopy(ledger_action)
    sheet_wrong_value['body']['cells']['review_state'] = 'Blocked'
    sheet_protected = copy.deepcopy(ledger_action)
    sheet_protected['body']['cells']['locked_note'] = 'overwritten'
    batch_action = next(a for a in c['actions'] if a.get('url', '').startswith(('hubspot/', 'slack/')))
    # The second policy carrier (Gmail) must be provably protected too: removing the SENT label with
    # a real native call makes the gmail body assertion fail, which is what binds the carrier.
    mail_id = c['entities']['policy_mail.policy']['id']
    policy_mail_assertions = [i for i, a in enumerate(assertions)
                              if a.get('type') == 'gmail_message_body_contains']
    mail_corrupt = {'method': 'POST', 'url': 'gmail/v1/users/me/messages/' + mail_id + '/modify',
                    'body': {'removeLabelIds': ['SENT']}}
    cases = [case('wrong_customer', 'wrong_target', c['reads'] + [wrong_target]),
             case('extra_customer', 'extra_member', [wrong_target], 'reference_complete'),
             case('wrong_policy', 'wrong_policy_result', c['reads'] + [wrong_value]),
             case('protected_field', 'protected_field_corruption', [corrupt], 'reference_complete'),
             case('policy_corruption','protected_field_corruption',[policy_corrupt],'reference_complete',[0]),
             case('required_effect_omitted','missing_member',c['reads']),
             case('ledger_wrong_value','wrong_target', [sheet_wrong_value], 'reference_complete', ledger_scored),
             case('ledger_protected_corruption','protected_field_corruption',[sheet_protected],'reference_complete',ledger_protected),
             case('ledger_effect_omitted','missing_member',c['reads'] + [batch_action],'initial',ledger_indices),
             case('policy_mail_corruption','protected_field_corruption',[mail_corrupt],'reference_complete',policy_mail_assertions),
             case('policy_mail_wrong_policy','wrong_policy_result',[wrong_value, mail_corrupt],'reference_complete',
                  sorted(set(policy_mail_assertions) | set(effect))),
             case('source_corruption','forbidden_action' if hr else 'protected_field_corruption',[source_corrupt],'reference_complete',source_assertions),
             case('alternate_read_order', 'equivalent_valid_path', list(reversed(c['reads'])) + c['actions'])]
    source_ref = c['entities']['join.source.cedar']
    rows = c['world']['bamboohr']['actions']['employee'] if hr else c['world']['salesforce']['contacts']
    position = next(i for i, row in enumerate(rows) if row['id'] == source_ref['id'])
    pointer = f'/bamboohr/actions/employee/{position}/params/trainingClearance' if hr else f'/salesforce/contacts/{position}/nda_status'
    replacements = {}
    for i, assertion in enumerate(assertions):
        if (hr and assertion.get('user') == target['id'] and 'status_text' in assertion or
                not hr and assertion.get('contact_id') == target['id'] and assertion.get('property') == 'jobtitle'):
            changed = copy.deepcopy(assertion); changed['status_text' if hr else 'value'] = alt_value
            replacements[str(i)] = changed
        elif hr and assertion.get('type')=='bamboohr_action_exists' and assertion.get('params',{}).get('employee_id')==source_ref['id']:
            changed=copy.deepcopy(assertion);changed['params']['trainingClearance']='Pending';replacements[str(i)]=changed
        elif not hr and assertion.get('type')=='salesforce_contact_field_equals' and assertion.get('contact_id')==source_ref['id'] and assertion.get('field')=='nda_status':
            changed=copy.deepcopy(assertion);changed['value']='Pending';replacements[str(i)]=changed
    # The ledger write is independent of the policy branch, so the alternate branch must perform it
    # too; otherwise the fixture would fail untouched obligations and could not prove the branch.
    fixture = {'public_policy_basis': {'public_request': True}, 'initial_state_replacements': {pointer: 'Pending'},
               'assertion_replacements': replacements, 'reference_actions': c['reads'] + [wrong_value, ledger_action]}
    source = {'task_instruction': instruction, 'initial_state': c['world'], 'assertions': assertions,
              'reference_actions': actions, 'forbidden_extra_actions': [corrupt, wrong_target],
              'native_construction_cases': cases, 'policy_fixtures': [fixture], 'tool_names': []}
    bindings = []
    for obligation in c['obligations']:
        oid = obligation['id']
        if oid.startswith('policy_mail.'):
            # Checked before the generic policy branches: the second carrier's obligations must bind
            # their own gmail assertion, not the primary Slack topic assertion.  The
            # `exception_changes_result` obligation additionally needs a `wrong_policy_result` case
            # whose failed indices cover both the business result and the carrier assertion.
            if oid.endswith('.exception_changes_result'):
                indices,refs=sorted(set(effect) | set(policy_mail_assertions)),['policy_mail_wrong_policy']
            elif oid.endswith('.policy_preservation'):indices,refs=policy_mail_assertions,['policy_mail_corruption']
            else:indices,refs=policy_mail_assertions,['alternate_read_order']
        elif oid.endswith('.policy_preservation'):indices,refs=[0],['policy_corruption']
        elif oid.endswith('.readable_policy'):indices,refs=[0],['alternate_read_order']
        elif oid.endswith('.source_preservation'):indices,refs=source_assertions,['source_corruption']
        elif oid.endswith('.required_effect'):indices,refs=effect,['required_effect_omitted']
        elif oid.endswith('.exception_changes_result'):indices,refs=effect,['wrong_policy']
        elif oid.endswith(('.wrong_scope_result','.non_target_preservation','.bounded_scope')):indices,refs=non_target,['extra_customer']
        elif oid.endswith(('.wrong_customer_result','.stable_identity')):indices,refs=effect+non_target,['wrong_customer']
        elif oid.endswith('.native_discoverability'):indices,refs=effect,['alternate_read_order']
        elif oid.startswith('ledger.'):
            if oid.endswith('.scored_row_state'):indices,refs=ledger_scored,['ledger_wrong_value','ledger_effect_omitted']
            elif oid.endswith('.protected_sibling_state'):indices,refs=ledger_protected,['ledger_protected_corruption']
            elif oid.endswith('.stable_row_identity'):indices,refs=ledger_indices,['ledger_effect_omitted']
            else:indices,refs=ledger_indices,['ledger_effect_omitted']
        else:indices,refs=list(range(len(assertions))),['alternate_read_order']
        bindings.append({'obligation_id': oid, 'requirement': 'Functional case obligation: ' + oid,
                         'public_basis': {'public_request': True}, 'assertion_indices': indices, 'case_ids': refs})
    return {'context': context, 'blueprint': bp, 'construction': c, 'source': source, 'bindings': bindings,
            'functional_only': True, 'independent_semantic_review_required': True, 'released': False}


def execute_example(example):
    from . import official_task_package as p
    from . import native_construction_cases as native
    from .official_alignment import normalize_runtime_value
    s = example['source']; official = p._official_imports()
    def reset():
        w = official['WorldState'](**normalize_runtime_value(copy.deepcopy(s['initial_state'])))
        w.meta.allowed_services = list(s['initial_state'])
        return w
    world = reset(); independent = reset(); initial_other = digest(independent.model_dump(mode='json'))
    responses, mutations = p._execute_official_action_sequence(official=official, world=world, actions=s['reference_actions'], label='construction.asset_example')
    score = p._official_score(initial_state=s['initial_state'], assertions=s['assertions'], world=world)
    if score['strict_pass'] is not True:
        raise ValueError('functional positive failed: ' + str(score))
    if digest(independent.model_dump(mode='json')) != initial_other:
        raise ValueError('asset task worlds share mutable state')
    cases = native.run_cases(initial_state=s['initial_state'], assertions=s['assertions'], reference_actions=s['reference_actions'],
                            reference_world=world, cases=s['native_construction_cases'], allowed_services=list(s['initial_state']),
                            instruction=s['task_instruction'])
    by_case={r['case_id']:r for r in cases['cases']}
    for binding in example['bindings']:
        for cid in binding['case_ids']:
            result=by_case[cid]
            if not result['expected_strict'] and not set(result['failed_assertion_indices']) & set(binding['assertion_indices']):
                raise ValueError('case fails an unrelated obligation: '+binding['obligation_id'])
    fixtures = p._run_policy_fixtures(initial_state=s['initial_state'], assertions=s['assertions'], reference_actions=s['reference_actions'],
                                     fixtures=s['policy_fixtures'], allowed_services=list(s['initial_state']), instruction=s['task_instruction'])
    # Prove the declared identity keys and policy text really appear in native
    # reads. Matching raw state alone would miss unobservable backing collections.
    read_results = []
    for action in example['construction']['reads']:
        import json
        raw = official['api_fetch'](independent, **action)
        value = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(value, dict) and (value.get('error') or value.get('ok') is False):
            raise ValueError('asset evidence read failed')
        read_results.append(value)
    import json
    rendered = json.dumps(read_results, ensure_ascii=False)
    for entity in example['construction']['entities'].values():
        if 'business_key' in entity and entity['business_key'] not in rendered:
            raise ValueError('asset identity evidence unreadable')
    for row in example['construction']['world'].get('slack', {}).get('channels', []):
        if row['topic'] not in rendered.replace('\\n', '\n'):
            raise ValueError('policy evidence unreadable')
    return {'strict_pass': True, 'state_isolation_passed': True, 'native_reads': read_results,
            'native_construction_case_results': cases, 'policy_fixture_results': fixtures,
            'mutation_count': mutations, 'reference_response_bindings': responses,
            'functional_only': True, 'semantic_accepted': False, 'released': False}
