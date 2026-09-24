"""Functional direction admission is necessary, never a released-QA decision."""
import json
from .construction_manifest import bound


def require_functional_direction(ref, direction):
    final = json.loads(bound(ref).read_text())
    if not final['complete'] or final['error'] is not None or final['actual_provider_calls'] < 1:
        raise ValueError('functional direction has no complete actual independent review')
    for key in ('trajectory', 'completion_seal'):
        bound(final[key])
    for key in ('validation', 'prompt', 'implementation'):
        bound(final['inputs'][key])
    validation = json.loads(bound(final['inputs']['validation']).read_text())
    if not validation['native_checks_passed']:
        raise ValueError('functional native validation failed')
    for row in validation['directions']:
        for key in ('record', 'child', 'native'):
            bound(row[key])
    decisions = final['decision']['expansion_decisions']
    chosen = [r for r in decisions if r['direction'] == direction]
    if (len(chosen) != 1 or chosen[0]['decision'] != 'accept' or chosen[0]['novelty'] != 'unresolved'
            or final['production_admitted'] is not False or final['released'] is not False):
        raise ValueError('functional acceptance missing or falsely promoted to QA release')
    return {'functional_direction_accepted': direction, 'independent_evidence': ref,
            'new_root_qa_review_and_distribution_still_required': True}
