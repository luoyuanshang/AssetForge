"""Split a frozen consumer binding into runtime-critical and orchestration layers.

Supervisor 2026-09-14 19:40 (highest-leverage item): the binding recorded all 597
sources with identical force, so editing the *controller* had exactly the same
consequence as editing the protocol or the native worker - every in-flight root
fail-closed.  Measured cost that day: contract39 -> 40 -> 41 -> 42 in ~40 minutes,
with contract41 stopped at 0 trajectories, i.e. the fix it carried could never be
observed.  Repair velocity exceeded verification velocity.

Layering rule:

* ``runtime_critical``: protocol, native worker, compile tool, asset definitions,
  catalog and transport.  A hash change here must fail closed, because a running
  root may spawn a child that would execute different code than the plan froze.
* ``orchestration``: controller / factory / runner / report / collection scripts.
  A hash change here is recorded as an auditable drift event but does **not** kill
  in-flight roots; it applies to the next spawn or the next wave.

The owner still verifies *every* source once at start-up, so a wave can never begin
on a drifted plan.
"""
from __future__ import annotations

from pathlib import Path

RUNTIME_CRITICAL_PREFIXES = (
    'assetforge/benchmark_factory/',
    'assetforge/artifacts/construction_assets/',
    'unified_benchmark_eval/ube/',
)
RUNTIME_CRITICAL_NAMES = {
    'admitted_catalog_v33_20260913.json',
    'catalog.json',
    'process_constructed_qa.py',
    'run_ownership_native_rpc.py',
    # Protocol / compile-path modules: classified by name as well as by directory
    # so the rule holds for flat sandbox copies and test fixtures too.
    'construction_manifest.py',
    'construction_assets.py',
    'construction_submission_context.py',
    'construction_app_asset.py',
    'construction_app_asset_v2.py',
    'native_asset_construction.py',
    'official_task_package.py',
    'agentic_runtime_compiler.py',
    'release_native_author_proxy.py',
    'turn_journal.py',
}
ORCHESTRATION_NAMES = {
    # Author-facing aids: they shape what the model reads (assets / skeletons) but
    # are not executed by the native compile or regression path, so editing them
    # must not fail-closed roots that are already authoring.
    'cell_skeletons.py',
    'contract_derived_assets.py',
    'construction_asset_contracts.py',
    'run_construction_factory.py',
    'run_parallel_construction_validation.py',
    'run_current_construction_stage.py',
    'run_current_construction_stage_v2.py',
    'run_current_construction_stage_v3.py',
    'run_current_constructed_qa_author_v2.py',
    'run_multiturn_agentic_qa_author.py',
    'run_constructed_qa_author.py',
    'run_constructed_qa_repair.py',
    'run_constructed_qa_reviewer.py',
    'run_agentic_markdown_reviewer.py',
    'run_release_reviews_compact.py',
    'revalidate_benchmark_native_qa.py',
    'bind_benchmark_qualified_qa.py',
}


def layer_of(path):
    """Return ``runtime_critical`` or ``orchestration`` for one source path."""
    text = str(path)
    name = Path(text).name
    if name in RUNTIME_CRITICAL_NAMES:
        return 'runtime_critical'
    if name in ORCHESTRATION_NAMES:
        return 'orchestration'
    for prefix in RUNTIME_CRITICAL_PREFIXES:
        if text.startswith(prefix) or ('/' + prefix) in text:
            return 'runtime_critical'
    return 'orchestration'


def split_sources(sources):
    """Partition a binding ``sources`` list into (critical, orchestration)."""
    critical, orchestration = [], []
    for ref in sources or []:
        (critical if layer_of(ref.get('path', '')) == 'runtime_critical' else orchestration).append(ref)
    return critical, orchestration


def verify(sources, *, verify_orchestration, on_orchestration_drift=None):
    """Verify a source list.

    ``verify_orchestration=True`` is used once by the owner at start-up (full
    binding).  In-flight children call it with ``False`` so that controller-level
    fixes no longer kill running roots; any orchestration mismatch is reported
    through ``on_orchestration_drift`` for the audit trail.
    """
    from .construction_manifest import bound

    critical, orchestration = split_sources(sources)
    for ref in critical:
        bound(ref)
    drifted = []
    for ref in orchestration:
        try:
            bound(ref)
        except Exception as error:  # noqa: BLE001 - reported, not fatal here
            drifted.append({'path': ref.get('path'), 'error': str(error)[:200]})
    if verify_orchestration and drifted:
        raise ValueError('orchestration source drift (owner start-up): '
                         + ', '.join(row['path'] for row in drifted[:5]))
    if drifted and on_orchestration_drift is not None:
        on_orchestration_drift(drifted)
    return {'runtime_critical': len(critical), 'orchestration': len(orchestration),
            'orchestration_drift': drifted}


# Sources whose content is cheap to hash and whose drift must never be missed.
# Everything else is guarded by a stat comparison against the wave-start
# manifest and only re-hashed when size/mtime moved.
HASH_ALWAYS_NAMES = {
    'construction_manifest.py',
    'official_task_package.py',
    'release_native_author_proxy.py',
    'process_constructed_qa.py',
    'run_ownership_native_rpc.py',
}


def build_stat_manifest(sources):
    """Hash every source once (wave start) and record size/mtime for stat checks."""
    import hashlib
    rows = {}
    for ref in sources or []:
        path = Path(ref.get('path', ''))
        stat = path.stat()
        rows[str(path)] = {
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'size': stat.st_size,
            'mtime_ns': stat.st_mtime_ns,
            'layer': layer_of(path),
        }
    return rows


def verify_via_manifest(sources, manifest, *, on_drift=None):
    """Cheap per-child verification: stat first, hash only when something moved.

    Supervisor 2026-09-14 20:18 §3.1: the per-root verification hashed all ~599
    frozen sources on every child spawn, which saturated GPFS metadata.  The wave
    owner hashes everything once; children compare size/mtime and only re-hash the
    sources that actually changed (plus a small always-hash subset that guards the
    compile/native path).
    """
    import hashlib
    drift = []
    orchestration_drift = []
    for ref in sources or []:
        path = Path(ref.get('path', ''))
        row = manifest.get(str(path))
        layer = layer_of(path)
        if row is None:
            (drift if layer == 'runtime_critical' else orchestration_drift).append(
                {'path': str(path), 'layer': layer, 'error': 'absent from wave-start manifest'})
            continue
        try:
            stat = path.stat()
        except OSError as error:
            (drift if layer == 'runtime_critical' else orchestration_drift).append(
                {'path': str(path), 'layer': layer, 'error': str(error)[:120]})
            continue
        moved = stat.st_size != row['size'] or stat.st_mtime_ns != row['mtime_ns']
        if moved or path.name in HASH_ALWAYS_NAMES:
            current = hashlib.sha256(path.read_bytes()).hexdigest()
            if current != row['sha256']:
                (drift if layer == 'runtime_critical' else orchestration_drift).append(
                    {'path': str(path), 'layer': layer,
                     'error': 'content hash differs from wave-start manifest'})
    # Layer discipline (supervisor 19:40 §4.1) must hold here too: orchestration
    # drift is REPORTED, runtime-critical drift is FATAL.  Measured 2026-09-14
    # 21:35: treating an orchestration edit as fatal killed 246 roots of contract53
    # even though the whole point of layering was to let controllers change freely.
    if orchestration_drift and on_drift is not None:
        on_drift(orchestration_drift)
    return {'checked': len(sources or []), 'hashed': sum(
        1 for ref in (sources or []) if Path(ref.get('path', '')).name in HASH_ALWAYS_NAMES),
        'drift': drift, 'orchestration_drift': orchestration_drift}
