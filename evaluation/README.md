# Evaluation — AutomationBench v1.0.6 (official alignment)

This directory is the **only** part of this repository that is coupled to an external
benchmark. Everything else is the task-construction pipeline and is independent of it.

The evaluation here is deliberately a thin driver: it does **not** reimplement the
benchmark. It loads the official runtime, uses the official environment class, the official
rubric and the official strict metric, and reports the official aggregate. The alignment
contract is written down in `OFFICIAL_ALIGNMENT.md` so the numbers can be trusted.

## What is measured

* **Dataset**: the public 600-task release, all six domains
  (sales, marketing, operations, support, finance, hr).
* **Environment**: the runtime's own `AutomationBenchEnv`, constructed exactly as the
  official entry point does — `max_turns=50`, `toolset="api"`, official rubric.
* **Strict metric**: `task_completed_correctly`, a 0/1 per task. This is the benchmark
  number. Partial-credit reward is recorded too, but it is **not** the reported score.
* **Aggregate**: `pass@1 = strict_tasks / total_tasks`. Several trials can be run; the
  aggregate is reported per trial and, when every trial is complete, averaged.

## Requirements

Two things are the operator's to supply, exactly as in the pipeline itself:

1. **The native runtime** for the benchmark version you intend to evaluate
   (`pip install` it, or point `ASSETFORGE_RUNTIME_ROOT` at the directory containing its
   package). The runner fails with a single explanatory message if it is missing.
2. **A model endpoint** — any OpenAI-compatible chat-completions or Responses endpoint:

   ```bash
   export EVAL_API_KEY=...            # your provider key
   # optionally EVAL_API_BASE_URL=... # default: the provider's public endpoint
   ```

## Run

```bash
python evaluation/run_evaluation.py \
    --model            my-model-name \
    --api-base-url     https://my-endpoint/v1 \
    --api-key-var      EVAL_API_KEY \
    --domains          all \
    --trials           1 \
    --max-concurrent   32 \
    --export-json      evaluation/out/results.json
```

Useful flags (mirroring the official entry point):

| Flag | Meaning |
|---|---|
| `--model` | model id sent to the endpoint |
| `--api-base-url` | OpenAI-compatible base URL |
| `--api-key-var` | name of the environment variable holding the key |
| `--api-key` | the key itself, if you prefer not to use an env var |
| `--domains` | `all`, or a comma-separated subset |
| `--num-examples` | limit the number of tasks (useful for a smoke run) |
| `--max-steps` | per-task turn budget (default 50, the official value) |
| `--trials` | how many independent trials to run |
| `--max-concurrent` | in-flight tasks |
| `--tasks` | evaluate an explicit list of task ids |
| `--recover` | resume an interrupted run from its per-task files |
| `--export-json` | write the per-task records and the aggregate |

## Output

```
evaluation/out/
  results.json          aggregate + run configuration
  tasks/<id>.json       one record per task: strict, reward, metrics, assertions, usage
```

Each task record keeps the strict flag, the full metric dict, the prompt and completion,
the assertion results and the token usage, so a reported number can be traced back to the
task that produced it.

## Aggregating separately

If you ran trials in separate processes, aggregate their per-task files:

```bash
python evaluation/aggregate.py evaluation/out/tasks/*.json
```

It prints `pass@1` over the files it is given, refusing to report a rate from an incomplete
set unless you pass `--allow-partial`.
