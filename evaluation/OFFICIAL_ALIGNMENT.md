# Official alignment contract

The numbers this evaluation produces are meant to be comparable with the benchmark's own
published numbers, so the driver is required to honour the contract below. Each item names
what the driver does and what it deliberately does **not** do.

## What the driver must not do

* **Not reimplement the environment.** It instantiates the runtime's own environment class and
  lets the runtime own the loop, tool routing and termination.
* **Not reimplement the scorer.** It calls the runtime's own rubric factory and reads the
  runtime's own metric out of the result. There is no local scoring code.
* **Not edit the runtime.** The runtime is imported as-is; nothing in this repository patches,
  wraps or monkey-patches its scoring path.
* **Not substitute the prompt.** The task prompt and the system prompt come from the runtime's
  dataset rows, unchanged.

## What the driver sets, and to which value

| Setting | Value | Why |
|---|---|---|
| per-task turn budget | `50` (`--max-steps`) | the runtime's own default for this task family |
| toolset | `api` (`--toolset`) | the runtime's own toolset used by the official run |
| rollouts per example | `1` | one rollout per task per trial; a "trial" is an independent repeat |
| task selection | the runtime's own dataset | the public task release, all six domains by default |
| strict metric | `task_completed_correctly` | the runtime's 0/1 metric, read from the result |
| aggregate | `strict / total` | plain accuracy over the tasks evaluated |

## Reporting rules

1. **The strict metric is the reported score.** The runtime also emits a denser
   partial-credit reward; it is recorded in each task record for analysis, but it is never the
   headline number.
2. **Incomplete runs are not scored.** If any trial evaluated fewer tasks than were selected,
   or a task carries an error, the summary marks the run incomplete and the mean is reported as
   `n/a`. `pass@1` is printed per trial either way, so a partial run is still inspectable.
3. **The denominator is stated.** Every result carries `task_count`, so a rate can be checked
   against the number of tasks actually evaluated.
4. **Trials are averaged, not cherry-picked.** With `--trials n` the reported mean is the
   arithmetic mean of the per-trial rates, and each per-trial rate is listed.

## Version binding

The driver reports `runtime_pin` in every result. The pin identifies the runtime build the run
used, so results from different builds are never silently pooled:

```bash
ASSETFORGE_RUNTIME_PIN=my-build python evaluation/run_evaluation.py ...
```

`ASSETFORGE_RUNTIME_ROOT` (where to import the runtime from) and `ASSETFORGE_RUNTIME_PACKAGE`
(its module name, if not discoverable) complete the configuration. All three are read in
`evaluation/runtime_bridge.py`; nothing else in the repository depends on the benchmark.
