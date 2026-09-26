# Markdown Agentic Rubric Protocol

> **P0 — Rubric = Author-only prompt.** An unqualified Rubric is the complete
> natural-language task-generation prompt shown to the QA Author. It is never
> a shared Author/Reviewer manual. Reviewer rules live in a separately
> versioned Reviewer Prompt, and mechanical gates live in code.

This protocol defines the role boundaries for the current Automation data
loop. Natural-language agents make semantic judgments; deterministic code
checks provenance, runtime behavior and release invariants without inventing
task meaning.

## Why the Author surface is natural language

Automation tasks are multi-step interactions. The Author must reason about the
user objective, simulated application affordances, dependencies between
observations, alternative valid paths, persistent state changes, forbidden
side effects, and the difference between a difficult task and an impossible
one. A fixed JSON schema can carry the result but cannot replace this judgment.

The Rubric therefore tells the Author what **single task** to realize: its
business family and domain, the simulated applications this cell admits, which
of them must carry the scored effects and how many, how many further
applications may only appear as readable background, the dependency topology,
deliverables, correct end state, protected scope, single-task size, difficulty,
originality, executability and anti-hack properties. It never states cell
quotas or the project-level distribution: how many tasks each cell needs,
domain x cardinality quotas, global ratios/bands/caps, release selection
policy, downstream training use or Reviewer procedure are controller and code
concerns. Those forbidden items must be **implemented and enforced in code**
(quota reservation and solving, the distribution gate, the selection gate, the
Reviewer Prompt, the release gate): their absence from the Rubric
is not a defect, their absence from code is. **Each Rubric version covers
exactly one cell / one task family and carries only that task's single-task
information**; different versions are authored separately and must not share
cross-cell text or carry any global information.
A separate Reviewer Prompt tells the Reviewer how to inspect the resulting QA
package and identify omissions or errors in the Rubric for the next immutable
version.

## Artifact roles

### Author Rubric

The Rubric is an agent-authored Markdown Author Prompt. It describes:

- the business family and domain of the single task it must realize (never its
  quota, i.e. never how many such tasks a cell needs);
- the allowed/scorable native simulated applications and each application's
  role, the required scored-application count N and the background allowance B
  (including the background-only list);
- dependency topology and workflow characteristics of that single task;
- the complete executable task-package deliverables;
- difficulty, solvability, diversity, originality and non-hack requirements;
- the public/private semantic boundary needed for faithful hidden scoring.

It must not contain Reviewer identity, review steps, accept/reject policy,
report format, revision-memo format, batch metadata, downstream training use,
a Cartesian task space, or a slot-filling template.

### Candidate QA

The QA Author reads one current domain-specific Rubric and writes a fresh,
complete executable QA package: a user-facing request plus the initial world,
native interaction surface, hidden state verifier and reset/test design. A
candidate is not a variable substitution of another candidate. The
deterministic runtime can test whether it executes, but cannot author or judge
its business meaning.

### Reviewer Prompt and Rubric-gap memo

The Reviewer uses its own versioned Reviewer Prompt. It reads the
frozen Author Rubric only as evidence of what the Author was instructed to do,
then examines the complete generated QA, native runtime evidence and permitted
aggregate benchmark references. It never receives any downstream consumer's
material.

The review produces a current-QA decision and, more importantly, identifies
where the Author Rubric was ambiguous, incomplete or misleading **about this
single task** (a missing allowed application or role, an unstated scored
application count, an unstated background allowance, a missing readable
evidence path, an unstated protected scope). A shortfall in the aggregate
distribution is not a Rubric defect: it belongs to the controller and the
selection gates. At a wave boundary, a Rubric agent aggregates only
generalized single-task counterexamples and authors the next immutable Author
Rubric.
Neither the Reviewer Prompt nor a raw review memo is spliced into an active
Rubric.

### Mechanical gates

Schema, official-runtime execution, reference path, counterexample, state-preservation,
reset, hash, deduplication and contamination checks live in code. They may
reject or quarantine an artifact but are not prose sections in the Rubric and
cannot silently add business requirements.

### Downstream use is not a Rubric input

Downstream stages consume accepted and frozen QA packages; their contracts are separate from
this one. Nothing about a downstream consumer may flow back into the Rubric, Author Prompt or
Reviewer Prompt.

## Integrity boundary

The Author Rubric may describe required *properties* of a world and verifier,
but it must never expose a benchmark answer, heldout state or concrete target
task verifier. Private compiler/scorer payloads cannot appear in the public
task request or any message visible to a downstream consumer. Audit JSON is
limited to hashes, paths, immutable versions and bounded statuses; substantive
Author and Reviewer judgments remain in their separate Markdown artifacts.

## Proposal-aligned loop and gates

1. **Benchmark Profile:** aggregate public benchmark analysis forms a
   target-distribution profile without copied tasks or heldout answers.
2. **Author Rubric:** a Rubric agent turns that profile into one immutable,
   domain-specific Author Prompt.
3. **Author:** the QA Author generates a fresh text–program–state task packet.
4. **Mechanical pre-gates:** official runtime tests schema, reference path,
   counterexamples, state preservation and reset.
5. **Reviewer Prompt:** an critic reviews the QA and diagnoses
   Rubric gaps.
6. **Freeze or certificate:** accepted QA is replayed, deduplicated and frozen;
   rejection yields a generalized counterexample certificate.
7. **Rubric evolution:** certificates are aggregated only at a wave boundary to
   produce the next immutable Author Rubric; a small canary must demonstrate
   lower defect recurrence or better yield before scaling.
8. **Downstream consumption:** only accepted and frozen QA packages are consumed downstream,
   under contracts held separately from this protocol.

This maps directly to the research proposal: the task packet operationalizes
**C1 / TPST**, role-separated generation and release gates operationalize
**C2 / Foundry**, and Reviewer counterexamples updating the next Rubric
operationalize **C3 / C³R**.
