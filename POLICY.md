# Project policy

This file states the invariants AssetForge is required to uphold. The stage modules read it at
start-up as a cheap check that they are running inside this repository, and it is the normative
reference when a change to a gate or a protocol is proposed.

## 1. Rubric = Author-only prompt

An unqualified *Rubric* is the complete natural-language task-generation prompt shown to the
Author. It describes **one** task: the business area, the applications and their roles, the
evidence and effects required, the correct terminal state, the protected scope, and the size.

A Rubric must **not** contain quota-level or project-level information. Specifically forbidden
inside a Rubric:

* how many tasks belong to a cell or a batch;
* distribution ratios, bands or caps;
* global totals for a corpus or a release;
* corpus-release rules or selection policy;
* the training purpose of the data.

These are controller concerns. They are enforced by code, not by asking the Author nicely, and a
Rubric that states them is rejected by a gate.

Reviewer instructions live in a **separately versioned** Reviewer prompt. The two documents must
never be spliced together, share text, or impersonate one another, and a mechanical gate must
never be written as a Reviewer paragraph and pasted into a Rubric.

## 2. The Reviewer has its own prompt and version

* The Reviewer prompt is versioned independently of the Rubric.
* The Reviewer inspects tasks that **actually executed**: it reproduces positive and negative
  paths on the native runtime.
* The Reviewer does not read the solver's trajectory.
* Reviewer findings may inform the next immutable Rubric version, but Reviewer procedure and
  output format never enter the Rubric.

## 3. Assets are the unit of composition

* A task is composed out of **admitted** assets, inside the capability the native runtime
  reports.
* An asset carries both a Markdown description (`ASSET.md`) — the artefact the Author and the
  Reviewer actually read — and a machine-readable `definition.json` — its parameter contract.
  Both are hash-bound in the release catalog, and a missing or altered file fails closed.
* An application the runtime marks action-only or check-less may hold background or act as a
  distractor, but must never carry the required effect or the decisive private fact.
* Asset admission requires native validation and a review; an asset that has not
  passed both is a candidate and cannot enter an Author wave.

## 4. Gates are the backstop

Admission, distribution, role-evidence, capability-binding and terminal-state constraints live in
**code**. A missing gate is an implementation defect; a Rubric that omits a corresponding
sentence is not.

Gates must fail closed: when a required input is absent, ambiguous or contradicts a bound hash,
the correct behaviour is to refuse, never to proceed on a default.

## 5. Provenance

* Every artefact a run consumes is bound by SHA-256, and consumers verify it.
* A run writes its outputs under its own run root; cross-run artefacts are promoted explicitly
  and are never written in place.
* Provider calls are attributed: a record states which model, route and attempt produced it.

## 6. Operator-supplied dependencies

AssetForge compiles and validates tasks. It does not implement the simulated world, the native
API surface or the scorer. Those come from a native runtime the operator supplies, wired in
through `assetforge/pipeline/native_runtime_interface.py`, and identified by
`ASSETFORGE_RUNTIME_PIN`. Model credentials come from the environment. Every module in this
repository imports cleanly whether or not the runtime is present.
