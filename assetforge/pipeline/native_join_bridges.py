"""Narrow native projections for genuine joins omitted by the seed-key graph.

Only adds Calendly event/invitee and Xero invoice/contact bridges, plus
Trello card and Drive file reference fields proven on native reset reads.
It does not invent records, rewrite policy, or establish semantic correctness.
"""
import copy
import json

CONTRACT = 'native-reset-verified-calendly-xero-bridges-and-card-file-references-v1'
ENV = 'QA18K_NATIVE_JOIN_BRIDGE_PROFILE'
GUIDANCE = ('Candidate selection keeps its existing predicates and bindings. Native '
    'Calendly invitees linked by event_id and Xero contacts linked by invoice contact_id '
    'may provide intermediate join records without invented predicates or duplicate IDs. '
    'Include successful reset GET probes exposing those records, their stable identities, '
    'email and foreign-key fields. Trello card description and Drive file/folder references '
    'count only when the same native card/file read exposes them. Keep all existing '
    'private-value, unique-selection, public-rule and source-bound policy-fixture requirements; '
    'native visibility does not prove that a relation is semantically appropriate.')


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


class NativeJoinBridgeIndex:
    def __init__(self, initial_state, reference_actions):
        from . import official_task_package as p
        self.p = p
        self.state = initial_state
        self.actions = reference_actions
        self.cache = {}
        self.probes = []

    def records(self, service):
        if service in self.cache:
            return self.cache[service]
        p = self.p
        official = p._official_imports()
        result = []
        for index, action in enumerate(self.actions):
            if str(action.get('method', '')).upper() != 'GET':
                continue
            if p._reference_action_target_service(action) != service:
                continue
            world = official['WorldState'](**copy.deepcopy(self.state))
            world.meta.allowed_services = p._seeded_simulated_application_names(self.state)
            before = world.model_dump(mode='python')
            packed = lambda v: p._canonical(v) if isinstance(v, (dict, list)) else v
            raw = official['api_fetch'](world, 'GET', action['url'],
                params=packed(action.get('params')), body=packed(action.get('body')))
            response = json.loads(raw)
            if isinstance(response, dict) and response.get('error'):
                raise ValueError(f'native join reset GET failed at reference index {index}')
            if world.model_dump(mode='python') != before:
                raise ValueError('native join reset GET mutated state')
            result.extend(objects(response))
            self.probes.append(dict(service=service, reference_index=index))
        self.cache[service] = result
        return result

    def witness(self, service, identity_field, identity, expected):
        if not isinstance(identity, str) or not identity:
            raise ValueError('native join witness requires a nonempty identity')
        if not any(record.get(identity_field) == identity and all(
                key in record and record[key] == value for key, value in expected.items())
                for record in self.records(service)):
            matching = [record for record in self.records(service)
                        if record.get(identity_field) == identity]
            diagnostic = dict(identity_field=identity_field, expected_identity=identity,
                required_fields=sorted(expected), identity_found=bool(matching),
                observed_identity_fields=sorted({key for record in matching for key in record}),
                successful_reset_get_indices=[row['reference_index'] for row in self.probes
                                               if row['service'] == service])
            raise ValueError(f'native join record projection unavailable for {service}; '
                + json.dumps(diagnostic, sort_keys=True, ensure_ascii=False))

    def augment(self, records):
        result = list(records)
        for service, record in records:
            state = self.state.get(service, {})
            if service == 'calendly' and record in state.get('scheduled_events', []):
                event_id = record.get('id')
                if not isinstance(event_id, str) or not event_id:
                    continue
                self.witness(service, 'uri', 'https://api.calendly.com/scheduled_events/' + event_id, {})
                for invitee in state.get('invitees', []):
                    if invitee.get('event_id') != event_id:
                        continue
                    iid = invitee.get('id')
                    if not isinstance(iid, str) or not iid:
                        raise ValueError('native join invitee identity missing')
                    uri = 'https://api.calendly.com/scheduled_events/' + event_id + '/invitees/' + iid
                    self.witness(service, 'uri', uri,
                        {'event': event_id, 'email': invitee.get('email')})
                    # The native event foreign key connects this bridge to the
                    # predicate-bearing event, not its ordinal in a seed list.
                    result.append((service, invitee))
            if service == 'xero' and record in state.get('invoices', []):
                contact_id = record.get('contact_id')
                if not isinstance(contact_id, str) or not contact_id:
                    continue
                self.witness(service, 'InvoiceID', record.get('invoice_id'),
                    {'Contact__ContactID': contact_id})
                for contact in state.get('contacts', []):
                    if contact.get('contact_id') != contact_id:
                        continue
                    self.witness(service, 'ContactID', contact_id,
                        {'EmailAddress': contact.get('email_address')})
                    result.append((service, contact))
        return result

    def reference_values(self, service, record):
        """Prove only the observed native aliases; arbitrary text stays excluded."""
        params = record.get('params', {})
        if not isinstance(params, dict):
            return set()
        values = []
        if service == 'trello' and record in self.state.get('trello', {}).get('actions', {}).get('card', []):
            identity = params.get('card')
            if params.get('desc'):
                self.witness(service, 'id', identity, {'desc': params['desc']})
                values = [identity, params['desc']]
        if service == 'google_drive' and record in self.state.get('google_drive', {}).get('actions', {}).get('find_multiple_files', []):
            identity = params.get('file')
            folder = params.get('folder')
            if folder:
                self.witness(service, 'id', identity, {'parents': [folder]})
                values = [identity, folder]
        return {self.p._canonical(v) for v in values if isinstance(v, str) and len(v.strip()) >= 3}
