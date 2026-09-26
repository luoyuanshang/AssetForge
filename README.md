# AssetForge

**Task synthesis for business-automation agents.**

AssetForge turns a business area plus a set of reusable **construction assets** into
executable, scoreable, trainable tasks. The pipeline is:

```
(Assets + Rubrics) → Author → Gate → Reviewer → QA
```

* **Assets + Rubrics** — An *asset* is a reusable building block: a Markdown description
  (`ASSET.md`) that states the business effect it produces and its parameter contract, plus a
  machine-readable `definition.json`. A *Rubric* is the Author-only generation prompt for one
  task. This repository ships 61 admitted assets.
* **Author** — assembles one original task out of the admitted assets, inside the capability
  the native runtime reports, then self-checks it before submitting.
* **Gate** — mechanical, fail-closed checks: asset admission and role evidence, application
  distribution, terminal-state gate, stage admission. Plain code, not a model.
* **Reviewer** — inspects tasks that actually ran, reproduces positive and negative paths
  natively, and returns a decision plus generalisable Rubric-gap findings.
* **QA** — repair dispatch and version admission: a rejected task is repaired onto the next
  immutable version, in a bounded number of rounds, with a lineage the gates verify.

The point of the design is that the **assets** are what the task is composed from, and that the
boundary between the Author's freedom and the gates' constraints is enforced by code rather than
by prompt convention. See "Design constraints" below.

## Quick start

```bash
git clone https://github.com/luoyuanshang/AssetForge.git && cd AssetForge
python -m pip install -e .          # the pipeline itself needs only the standard library

# 1. bring your own model endpoint (any OpenAI-compatible one)
export ASSETFORGE_API_KEY=...
export ASSETFORGE_API_BASE_URL=https://your-endpoint/v1
export ASSETFORGE_MODEL=my-model

# 2. point at a native runtime (see below)
export ASSETFORGE_RUNTIME_ROOT=/path/that/contains/the/runtime/package

# 3. author one task from a Rubric
python -m assetforge.tools.run_author \
    --rubric examples/rubric_support.md --domain support \
    --run-root runs/demo --ordinal 1

# or drive a batch from a frozen plan
python -m assetforge.tools.run_constructed_qa_author \
    --plan examples/plan.json --plan-sha256 "$(cat examples/plan.sha256)" \
    --cell support_demo --run-root runs/plan-demo
```

The Author stage carries its **own** agent loop (`assetforge/agent/`), so nothing but a model
endpoint is required to run it: the loop calls `search` / `visit` / `code_exec`, the read-only
contract inspector, and finally `compile_and_test_task_package`, which validates the authored
task against the native runtime and the scorer before it is kept. A deployment that already has
an agent framework can inject it instead.

Two things are the operator's to supply, exactly as they are for any pipeline of this kind:

1. **A model endpoint.** Credentials and base URL are read from the environment.
2. **A native runtime.** AssetForge *compiles and validates* tasks; it does not implement the
   simulated world, the native API surface or the scorer. Those live in a separate native
   runtime, wired in through one interface —
   `assetforge/pipeline/native_runtime_interface.py`:

   ```bash
   export ASSETFORGE_RUNTIME_ROOT=/path/that/contains/the/runtime/package
   # only if its module name is not discovered automatically:
   export ASSETFORGE_RUNTIME_PACKAGE=my_runtime
   export ASSETFORGE_RUNTIME_PIN=my-build        # recorded in every artefact this pipeline emits
   ```

   Every module imports cleanly whether or not the runtime is present. The steps that genuinely
   need it — compiling an authored task, executing a review — say so plainly and tell you what to
   set; they never surface a raw import error.

## Design constraints

These are enforced **in code**, not by convention.

1. **Rubric = Author-only prompt.** A Rubric describes *this one task*. Quota-level and
   project-level information — tasks per cell, distribution ratios, global totals,
   corpus-release rules, training purpose — is forbidden inside a Rubric and rejected by a
   code gate.
2. **The Reviewer has its own prompt and version.** Reviewer rules and mechanical gates are
   versioned separately and must never be spliced together. The Reviewer inspects tasks that
   executed; it reads neither a solver's output nor anything the data is later used for.
3. **Assets are the unit of composition.** A task is built out of admitted assets, inside the
   capability the runtime reports. An application the runtime marks action-only or check-less
   may hold background or act as a distractor, but must never carry the required effect or the
   decisive private fact.
4. **Gates are the backstop.** Admission, distribution, role-evidence and binding constraints
   live in code. A missing gate is an implementation defect.

## Repository layout

```
assetforge/
  pipeline/       stage modules, gates, and the runtime interface
  tools/          one thin CLI entry point per stage
  protocols/      the Agentic Rubric protocol and the Reviewer prompt
  artifacts/      the 61 admitted assets and their release catalog
evaluation/       benchmark evaluation driver (see below)
verification/     the self-check used to verify this repository
```

## Stages and entry points

| Stage | Entry point | What it does |
|---|---|---|
| Author | `python -m assetforge.tools.run_author` | one Author session from a Rubric |
| Author (plan) | `python -m assetforge.tools.run_constructed_qa_author` | the same session driven from a frozen, hash-bound plan |
| Gate | `python -m assetforge.tools.validate_construction_assets`, `…admit_construction_assets`, `…gate_automation_18k_distribution` | mechanical, fail-closed checks |
| Reviewer | `python -m assetforge.tools.run_constructed_qa_reviewer`, `…review_construction_assets` | review of tasks that executed |
| QA | `python -m assetforge.tools.process_constructed_qa`, `…run_construction_factory` | repair dispatch and version admission |

Every one of these runs whether or not the native runtime is installed; only the steps that
compile or execute a task need it.

## Evaluation

`evaluation/` runs a task-level benchmark evaluation against a native runtime and reports the
strict 0/1 metric. It is deliberately thin — it uses the runtime's own environment, rubric and
metric rather than reimplementing any of them — and the alignment contract it honours is
written down in [`evaluation/OFFICIAL_ALIGNMENT.md`](evaluation/OFFICIAL_ALIGNMENT.md).

```bash
export EVAL_API_KEY=...
python evaluation/run_evaluation.py \
    --model my-model --api-base-url https://your-endpoint/v1 \
    --domains all --trials 1 --export-json evaluation/out/results.json
```

See [`evaluation/README.md`](evaluation/README.md).

## Verifying the repository

```bash
python verification/verify_package.py
```

Checks that every module compiles and imports with the runtime absent, that the runtime
interface reports the pin, that the asset catalog loads and every hash binding verifies, that
each asset carries both `ASSET.md` and `definition.json`, and that no non-English text or
third-party identity remains.

## Assets

`assetforge/artifacts/construction_assets/` holds the admitted assets, and
`assetforge/artifacts/construction_catalog.json` is the release catalog that binds each
`definition`, `description` and implementation by SHA-256. Both files are required per asset:
`ASSET.md` is the artifact the Author and the Reviewer actually read, and `definition.json` is
the parameter contract. A tampered or incomplete asset set fails closed at load time.

## Licence

MIT — see [LICENSE](LICENSE).
