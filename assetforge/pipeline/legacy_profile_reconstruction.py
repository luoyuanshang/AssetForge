"""Reconstruct a declared execution profile for legacy QA that lost its preflight.

`qa_repair_profile.bound_source_profile` proves the original Author profile from
the authoring wave's `preflight.json`.  Early waves
(`automation_official1000_20260805_r1`, early `automation_qa18k_native_diversity_*`
runs) never wrote one, so 8,812 already-native-passing QA can never be qualified
even though their tasks, rubrics, author receipts and native evidence are all
still sealed and hash-bound.

This module does NOT invent a profile.  It re-derives the declared profile from
the frozen Rubric plus the frozen Author config with the same
`OfficialTaskPackageTool` that produced the original profile, records every
input hash in an immutable reconstruction receipt, and labels the provenance as
`reconstructed-from-frozen-rubric-and-author-config-v1`.  The substantive gate
is unchanged and still executed: the whole package must recompile to an
identical task (public request, initial state, assertions, tools) and pass the
full native profile run.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
METHOD = 'reconstructed-from-frozen-rubric-and-author-config-v1'
CONTRACT = 'legacy-reconstructed-root-author-execution-profile-v1'
REQUIRE_FLAGS = ('require_scorer_counterexamples', 'require_contract_closure', 'require_semantic_graph',
                 'compact_official_task_source', 'require_selection_contract')
# Waves authored before these gates existed did not record them.  Every one of
# them is a `store_true` CLI flag in the Author tool, so the historical default
# contract is False; the reconstruction receipt records which keys had to be
# defaulted so nobody can mistake this for a recorded original value.
LEGACY_DEFAULT_FLAGS = {key: False for key in REQUIRE_FLAGS}


def frozen_profile_flags(config):
    flags = {}
    defaulted = []
    for key in REQUIRE_FLAGS:
        if key in config:
            flags[key] = config[key]
        else:
            flags[key] = LEGACY_DEFAULT_FLAGS[key]
            defaulted.append(key)
    # A compiled runtime source cannot satisfy the semantic-graph requirement.
    if flags['require_semantic_graph']:
        raise ValueError('legacy reconstruction cannot supply a semantic graph')
    return flags, defaulted


def _ref(path):
    path = Path(path).resolve()
    return {'path': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def reconstruct_source_profile(*, task_path, rubric_path, author_receipt, candidate_path, candidate_id,
                               domain, output_dir):
    from .official_task_package import OfficialTaskPackageTool
    task_path, rubric_path, author_receipt = Path(task_path), Path(rubric_path), Path(author_receipt)
    author = json.loads(author_receipt.read_text())
    config = author.get('config') or {}
    flags, defaulted = frozen_profile_flags(config)
    rubric_text = rubric_path.read_text()
    tool = OfficialTaskPackageTool(candidate_relative_path=str(Path(candidate_path).resolve().relative_to(ROOT)),
                                   candidate_id=candidate_id, domain=domain,
                                   rubric_sha256=hashlib.sha256(rubric_path.read_bytes()).hexdigest(),
                                   rubric_text=rubric_text, **flags)
    profile = copy.deepcopy(tool._rubric_mechanical_profile)
    if not isinstance(profile, dict):
        raise ValueError('reconstruction derived a non-object execution profile')
    # A pre-profile-era Rubric declares no execution markers at all.  Recording
    # that fact is the faithful reconstruction: we declare no profile instead of
    # inventing one.  Every substantive gate still runs (mechanical
    # compatibility, full native execution, recompile identity, independent
    # review, quality holds).
    provenance = METHOD if profile else 'legacy-wave-without-execution-profile-v1'
    task_sha = hashlib.sha256(task_path.read_bytes()).hexdigest()
    receipt = {
        'schema_version': 'legacy-profile-reconstruction-receipt-v1',
        'method': provenance,
        'task': _ref(task_path),
        'rubric': _ref(rubric_path),
        'author_receipt': _ref(author_receipt),
        'candidate': _ref(candidate_path),
        'author_config_sha256': hashlib.sha256(
            json.dumps(config, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        'mechanical_profile': profile,
        'profile_flags': flags,
        'defaulted_profile_flags': defaulted,
        'claim': ('declared profile derived deterministically from the frozen rubric and the frozen Author '
                  'config; it replaces a preflight that this wave never wrote and does not assert the '
                  'original authoring intent'),
    }
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / (task_sha + '.json')
    if target.exists():
        existing = json.loads(target.read_text())
        if existing.get('task', {}).get('sha256') != task_sha or existing.get('method') != provenance:
            raise ValueError('existing reconstruction receipt does not match this task')
        if existing.get('mechanical_profile') != profile:
            raise ValueError('reconstruction is not deterministic for this task')
    else:
        with target.open('x') as handle:
            json.dump(receipt, handle, ensure_ascii=False, sort_keys=True)
    return {
        'contract': CONTRACT,
        'provenance': provenance,
        'ancestry': [{'path': str(task_path.relative_to(ROOT)), 'sha256': task_sha,
                      'task_id': json.loads(task_path.read_text())['task_id']}],
        'original_preflight': None,
        'mechanical_profile': profile,
        'reconstruction_receipt': _ref(target),
    }
