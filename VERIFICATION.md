# Verification

Run it yourself:

```bash
python verification/verify_package.py
```

## Result

```
[1] compile+import (runtime absent): 104 compiled, 104 imported
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

ALL CHECKS PASSED
```

What each check establishes:

1. **The pipeline runs without the native runtime.** Every module compiles and imports with the
   runtime absent, so the pipeline is usable as a method on its own. The scan fails if it finds
   nothing to scan, so a path typo cannot produce a false pass.
2. **The runtime binding is ours.** `runtime_pin()` returns this repository's own identifier,
   not a third party's release.
3. **The asset catalog is intact.** `load_catalog` verifies the catalog hash, the pin, and the
   hash of every `definition`, `description` and implementation reference, so a tampered or
   incomplete asset set fails closed.
4. **Both files are required per asset.** `ASSET.md` is what the Author and the Reviewer read;
   `definition.json` is the parameter contract.
5. **The pipeline reads as a standalone method.** The repository is English-only, and outside
   `evaluation/` it carries no benchmark identity at all.

## Also checked by hand

| Check | Result |
|---|---|
| Operator supplies a runtime (`ASSETFORGE_RUNTIME_ROOT`) | the interface returns that runtime's world-state type, assertion handlers and domain dataset |
| Operator re-pins (`ASSETFORGE_RUNTIME_PIN=my-build`) | `construction_assets.COMMIT` follows the pin |
| Pin does not match the catalog | `load_catalog` **rejects** with "incompatible catalog runtime" — fail-closed, as intended |
| Operator supplies only `ASSETFORGE_*` variables | the evaluation driver picks up model, base URL and key with no flags |
| Evaluation driver end to end | ran against a local OpenAI-compatible stub: 600-task dataset loaded, N tasks selected, rollouts executed, strict scores and per-domain breakdown written |

## Evaluation-section check

The evaluation driver was exercised against a stub endpoint to confirm the whole path works
without a real provider: dataset resolution, task selection, environment construction, rollout,
strict-metric extraction, per-domain aggregation and JSON export. `evaluation/OFFICIAL_ALIGNMENT.md`
records the contract it must honour, and the verifier enforces that benchmark-specific naming
stays confined to `evaluation/`.
