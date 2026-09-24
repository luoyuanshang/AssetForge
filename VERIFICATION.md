# Verification

Run it yourself:

```bash
python verification/verify_package.py
```

## Result

```
[1] compile+import (runtime absent): 110 compiled, 110 imported
  ok   all modules compile and import
[2] runtime pin = 'assetforge-runtime-1'; runtime available = False
  ok   runtime pin is ours
[3] catalog loaded: 61 assets, 0 dependencies
  ok   catalog holds 61 assets
[4] assets with both ASSET.md and definition.json: 61/61
  ok   every asset has ASSET.md and definition.json
[5] non-English text: 0; benchmark identity outside evaluation/: 0
  ok   repository is English-only
  ok   pipeline is free of benchmark identity (outside evaluation/)
[6] example plan bound to its Rubric: True
  ok   the example plan is bound to its Rubric by hash
[7] author-stage runner present: True
  ok   the author stage carries its own agent loop

ALL CHECKS PASSED
```

What each check establishes:

1. **The pipeline runs without the native runtime.** Every module compiles and imports with the
   runtime absent. The scan fails if it finds nothing to scan, so a path typo cannot produce a
   false pass.
2. **The runtime binding is ours**, not a third party's release.
3. **The asset catalog is intact.** `load_catalog` verifies the catalog hash, the pin, and the
   hash of every `definition`, `description` and implementation reference, so a tampered or
   incomplete asset set fails closed.
4. **Both files are required per asset.** `ASSET.md` is what the Author and the Reviewer read;
   `definition.json` is the parameter contract.
5. **The pipeline reads as a standalone method**: English-only, and with no benchmark identity
   outside `evaluation/`.
6. **The shipped example is internally consistent**: its plan binds its Rubric by hash.
7. **The Author stage carries its own agent loop**, so it does not depend on a framework that is
   not in this repository.

## Exercises run by hand

| Exercise | Result |
|---|---|
| Every CLI entry point `--help`, **without** the runtime | 10 / 10 |
| Every CLI entry point `--help`, **with** the runtime | 10 / 10 |
| Example plan, dry run (`--dry-run`) | plan, cell, Rubric and catalogue all verify; no model call |
| **Author session end to end** against a local OpenAI-compatible endpoint | the loop issued `code_exec`, received the result, and continued to its turn budget |
| **Evaluation end to end** against a local endpoint | 600-task dataset loaded, tasks selected, rollouts executed, strict scores and per-domain breakdown written to JSON |
| Operator supplies only `ASSETFORGE_*` variables | the driver picks up model, base URL and key with no flags |
| Operator re-pins (`ASSETFORGE_RUNTIME_PIN=my-build`) | `construction_assets.COMMIT` follows the pin |
| Pin does not match the catalog | `load_catalog` **rejects** with "incompatible catalog runtime" — fail-closed |
| Runtime absent, `ASSETFORGE_RUNTIME_ROOT` ignored | modules that need the runtime raise one explanatory error rather than an import error from deep inside a library |

## What the runtime is for

AssetForge compiles and validates tasks; it does not implement the simulated world, the native API
surface or the scorer. Those come from a native runtime the operator supplies, wired in through
`assetforge/pipeline/native_runtime_interface.py` and identified by `ASSETFORGE_RUNTIME_PIN`. Model
credentials come from the environment. Steps that need the runtime — compiling a task, executing a
review — will say so plainly when it is absent; everything else runs.
