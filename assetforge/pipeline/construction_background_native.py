"""Official execution evidence for structural background; no private task scorer."""
import copy
import json
from .construction_assets import digest, require

CONTRACT = 'native-readable-background-v1'


def readable_record_seen(responses, entity):
    """Match native identity and business projection on the SAME decoded object."""
    def objects(value):
        if isinstance(value, dict):
            yield value
            for item in value.values(): yield from objects(item)
        elif isinstance(value, list):
            for item in value: yield from objects(item)
    fields = {k: v for k, v in entity['record'].items() if k != 'id' and
              isinstance(v, (str, int, float)) and str(v).strip()}
    for response in responses:
        for row in objects(json.loads(response)):
            if str(row.get('id', '')) != str(entity['id']): continue
            observed = {}
            for key, value in fields.items():
                if key not in row: continue
                actual = row[key]
                if isinstance(actual, dict) and 'value' in actual: actual = actual['value']
                observed[key] = actual == value
            if observed and all(observed.values()): return True
    return False


def validate_evidence(evidence, construction, source):
    require(isinstance(evidence, dict) and evidence.get('contract') == CONTRACT, 'background native evidence missing')
    require(evidence.get('construction_sha256') == digest(construction) and
            evidence.get('source_sha256') == digest(source), 'background evidence input mismatch')
    required = {o['id'] for o in construction['obligations'] if o.get('kind') == 'structural_background'}
    rows = evidence.get('obligations', [])
    require(len(rows) == len(required) and {r['obligation_id'] for r in rows} == required,
            'background evidence does not cover exact obligations')
    for row in rows:
        obligation = next(o for o in construction['obligations'] if o['id'] == row['obligation_id'])
        require(row.get('business_state_unchanged') is True and row.get('all_records_read') is True and
                row.get('read_actions_sha256') == digest(obligation['reads']) and
                set(row.get('observed_entities', [])) == set(obligation['entity_symbols']) and
                len(row.get('response_hashes', [])) == len(obligation['reads']),
                'background read-back or non-mutation proof incomplete')
    require(evidence.get('combined_correct_strict') is True and evidence.get('read_only_strict') is False,
            'background composition must retain the real task obligation')
    return True


def run_background_native(construction, source):
    from . import official_task_package as native
    from .release_runtime import require_verified_protocol
    require_verified_protocol()
    official = native._official_imports()
    state = source['initial_state']
    world = official['WorldState'](**copy.deepcopy(state))
    world.meta.allowed_services = list(state)
    rows = []
    for obligation in construction['obligations']:
        if obligation.get('kind') != 'structural_background':
            continue
        before = world.model_dump(mode='json')
        responses = []
        for action in obligation['reads']:
            response = official['api_fetch'](world, action['method'], action['url'],
                params=copy.deepcopy(action.get('params')), body=copy.deepcopy(action.get('body')))
            # api_fetch returns a JSON string even for unsuccessful HTTP responses.
            parsed = json.loads(response)
            require(not (isinstance(parsed, dict) and (parsed.get('error') or
                    isinstance(parsed.get('status'), int) and parsed['status'] >= 400)),
                    'background discovery operation failed')
            responses.append(response)
        after = world.model_dump(mode='json')
        # The fetch layer logs transport metadata; all actual application state must stay identical.
        before.pop('meta', None); after.pop('meta', None)
        require(before == after, 'declared background read mutates business state')
        seen = []
        for symbol in obligation['entity_symbols']:
            entity = construction['entities'][symbol]
            require(readable_record_seen(responses, entity),
                    'background entity identity and meaningful content not readable')
            seen.append(symbol)
        rows.append({'obligation_id': obligation['id'], 'business_state_unchanged': True,
            'all_records_read': True, 'observed_entities': seen,
            'read_actions_sha256': digest(obligation['reads']),
            'response_hashes': [digest(response) for response in responses]})
    read_only = native._official_score(initial_state=state, assertions=source['assertions'], world=world)
    native._execute_official_action_sequence(official=official, world=world,
        actions=source['reference_actions'], label='background.composed.correct')
    result = native._official_score(initial_state=state, assertions=source['assertions'], world=world)
    evidence = {'contract': CONTRACT, 'construction_sha256': digest(construction),
        'source_sha256': digest(source), 'obligations': rows,
        'combined_correct_strict': result['strict_pass'], 'read_only_strict': read_only['strict_pass']}
    validate_evidence(evidence, construction, source)
    return evidence
