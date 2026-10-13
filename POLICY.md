# Project policy

## Author Rubric

A Rubric describes one task for the Author: business context, available applications and
their roles, dependencies, deliverables, final-state requirements, protected scope, size,
originality, and how to obtain reusable assets. It is not a solver instruction.

Project quotas, distribution targets, release rules, training purposes, and Reviewer
procedures belong in controller configuration or a separate Reviewer prompt.
Rubric text is never used as a configuration switch. Boundary checks are read-only.

## Composition

ASSET.md and definition.json are both required. Their identities, versions, and
implementation hashes are verified before generation. Asset parameters describe business
records and effects. The controller generates stable identities and joins compatible
fragments. Conflicting identities, writes, and protection requirements fail closed.

## Gate and Reviewer

The Gate checks format, composition, and the configured runtime contract. It reports
the independent failures it finds together. Compilation is not a claim that a task has
been solved or received a benchmark score.

The Reviewer has a separate model configuration and prompt. It evaluates the constructed
task and its business meaning. Missing, malformed, or contradictory model review cannot
produce an accepted QA. Rubric-gap findings may inform a future Rubric; they are not
inserted into the current Author specification.

## Repair and publication

A fixed attempt limit bounds each run. Feedback identifies the actual task defect.
Rejected and failed runs publish no QA. A task is published only after both Gate and
Reviewer pass. Per-attempt inputs and outputs remain available within the run directory.

## Provenance

Input files are hash-bound, model requests and responses are retained with token usage,
and outputs are immutable. Credentials are supplied through environment variables and
are excluded from artifacts. Run directories are not committed.

## Runtime boundary

Production environments supply an explicit compile adapter. The included worksheet
adapter is an example for integration testing; it makes no production coverage claim.
Benchmark evaluation uses the separate evaluation driver and its native runtime.
