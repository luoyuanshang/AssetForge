# AssetForge

Task synthesis for business-automation agents:

~~~
(Assets + Rubrics) -> Author -> Gate -> Reviewer -> QA
~~~

AssetForge combines 61 reusable construction assets with a task-specific Author Rubric.
Assets supply records, stable identities, field constraints, and terminal-state assertions.
The Author chooses the business task and asset parameters. The controller composes those
fragments, checks compatibility through a runtime adapter, requests a separate model review,
and publishes a QA only after both stages pass. Rejected submissions receive actionable
feedback within a bounded repair budget.

## Code, model, and data availability

The public release includes the pipeline code and 61 reusable construction assets.
An AssetForge SFT model is available on
[Hugging Face](https://huggingface.co/gokoururi123/AssetForge).

The released pipeline can be used to reproduce the task-construction workflow
and generate new task datasets using task-specific Author Rubrics, model
providers, and a compatible runtime adapter.

The two training datasets used in the paper have not been publicly released, and
we do not plan to release them in the near term. The submitted manuscript
incorrectly describes these datasets as released; we apologize for the confusion.
The filenames and SHA-256 hashes in the paper identify the datasets used in our
experiments, rather than publicly downloadable files.

The model release supports evaluation but does not replace access to the exact
training data for reproducing the SFT experiments.

## Quick start

Python 3.10 or newer is required. The generation package uses the standard library.

~~~bash
python -m pip install -e .

export ASSETFORGE_API_BASE_URL=https://your-provider.example/v1
export ASSETFORGE_API_KEY=...
export ASSETFORGE_MODEL=your-author-model
export ASSETFORGE_REVIEWER_MODEL=your-reviewer-model

assetforge-run --rubric examples/rubric_support.md \
    --runtime demo --assets sheet_row_state --output runs/support-001
~~~

The Reviewer may use the same provider credentials, or its own ASSETFORGE_REVIEWER_API_KEY
and ASSETFORGE_REVIEWER_API_BASE_URL. A Reviewer model must be configured explicitly.
There is no automatic acceptance when model review is unavailable.

The bundled demo adapter checks worksheet record and assertion bindings. It is intended
for examples and integration tests and supports Google Sheets only. Other applications
require an operator-supplied runtime adapter.

## Assets

The library is in assetforge/artifacts/construction_assets/. Each asset has an English
ASSET.md and a definition.json parameter contract. The construction catalog binds both
files and their implementation by SHA-256. Application record fields are distributed
alongside the assets; no private endpoint or credential is embedded.

The Author receives the complete descriptions and parameter contracts of the selected
assets. Use --assets to select a task-appropriate subset. A task may combine several
assets; the resulting fragments must agree on identities, values, and protected fields.
An asset definition describes a reusable capability, rather than a complete task.

Validate the library:

~~~bash
assetforge-assets
~~~

Catalog integrity is distinct from compatibility with a production runtime. The chosen
runtime adapter checks the constructed task; native admission and application coverage
depend on the operator's runtime.

## Task format and stages

The Author returns a JSON object with instruction and assets, plus optional
extra_initial_state and extra_assertions. Every asset selection specifies id, version,
alias, reason, and parameters. The controller owns task identifiers, seed, and business time.

The Gate constructs the asset fragments and checks the task format, composition, and
runtime contract. Diagnostics contain the affected field, expected value, and actual value.
Compilation checks structural compatibility; the model Reviewer separately checks business
meaning, public scope, scoring coverage, originality, and Rubric gaps.

The published qa.json contains task_id, instruction, initial_state, and assertions.
It describes a task and its terminal-state conditions. The runtime adapter determines how
that task is loaded and scored in its environment.

Each run has a unique output directory containing bound inputs, per-attempt candidates,
Gate reports, model-review decisions, model request/response events, token usage, and the
final result. A rejected or failed run has no qa.json. Existing runs are never overwritten.
Run artifacts are excluded from Git.

Use --resume to continue an interrupted run with exactly matching bound inputs. Matching
model responses are reused, completed runs are preserved, and input or output drift is refused.

## Runtime adapters

Pass --runtime your_package:make_runtime. The factory returns an object implementing:

~~~python
class RuntimeAdapter:
    def describe(self):
        return {"name": "my-runtime", "applications": ["..."]}

    def compile(self, task):
        # Return all compatibility diagnostics, or [] when the task is valid.
        return []
~~~

The adapter must validate its actual application schemas and assertion contracts.
It receives a copy of the constructed task and must not change the task being published.
Its configuration is separate from the Author Rubric.

## Validation

~~~bash
python -m unittest discover -s tests -v
python verification/verify_package.py
~~~

Tests cover catalog hashes, documented asset parameters, task compilation, full QA
publication, repair, rejection, immutable outputs, token usage, and the CLI through a local
HTTP model endpoint. Scripted model responses test the software flow; they are not model
quality measurements or benchmark scores.

## Evaluation

The separate evaluation/ driver uses an operator-installed benchmark runtime and its own
environment, scoring, and dataset. See evaluation/README.md. The worksheet demo does not
replace that runtime or reproduce benchmark scores.

## License

MIT. See LICENSE.
