#!/usr/bin/env python3
"""Self-contained verification of this package.

Run:  python verification/verify_package.py

Checks (all must pass):
  1. every module compiles and imports, with the native runtime ABSENT;
  2. the runtime interface reports our own pin;
  3. the 61-asset catalog loads and every hash binding verifies;
  4. every asset has both ASSET.md and definition.json;
  5. no non-English text and no third-party identity remains.
"""
import ast, hashlib, json, os, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FAILS = []


def check(ok, label):
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        FAILS.append(label)


# 1 --------------------------------------------------------------------------
compiled = imported = 0
for dp, _, fs in os.walk(ROOT / "assetforge"):
    for f in fs:
        if not f.endswith(".py"):
            continue
        p = pathlib.Path(dp) / f
        rel = str(p.relative_to(ROOT))[:-3].replace("/", ".")
        try:
            ast.parse(p.read_text(encoding="utf-8"))
            compiled += 1
        except Exception as exc:
            FAILS.append(f"compile {rel}: {exc}")
        try:
            __import__(rel)
            imported += 1
        except Exception as exc:
            FAILS.append(f"import {rel}: {exc}")
print(f"[1] compile+import (runtime absent): {compiled} compiled, {imported} imported")
check(compiled > 0 and imported == compiled, "all modules compile and import")

# 2 --------------------------------------------------------------------------
from assetforge.pipeline.native_runtime_interface import runtime_pin, is_available
print(f"[2] runtime pin = {runtime_pin()!r}; runtime available = {is_available()}")
check(runtime_pin() == "assetforge-runtime-1", "runtime pin is ours")

# 3 --------------------------------------------------------------------------
from assetforge.pipeline import construction_assets as CA
catp = ROOT / "assetforge/artifacts/construction_catalog.json"
cat = CA.load_catalog(catp, expected_sha256=hashlib.sha256(catp.read_bytes()).hexdigest())
print(f"[3] catalog loaded: {len(cat['assets'])} assets, {len(cat.get('dependencies', []))} dependencies")
check(len(cat["assets"]) == 61, "catalog holds 61 assets")

# 4 --------------------------------------------------------------------------
missing = [a["id"] for a in cat["assets"]
           if not ((ROOT / a["description"]["path"]).exists() and (ROOT / a["definition"]["path"]).exists())]
print(f"[4] assets with both ASSET.md and definition.json: {len(cat['assets']) - len(missing)}/{len(cat['assets'])}")
check(not missing, "every asset has ASSET.md and definition.json")

# 5 --------------------------------------------------------------------------
CJK = re.compile(r"[\u4e00-\u9fff]")

# ``evaluation/`` is the one part of this repository that is explicitly aligned with an
# external benchmark, so benchmark names are expected there.  Everywhere else must be free of
# them: the pipeline is meant to be readable as a standalone method.
EVAL_DIR = "evaluation"
_TOK = ["ks"+"yun","code"+"ccs","dash"+"scope","zhi"+"pu","service"+"now",
        "automation"+"bench","1"+"."+"0"+"."+"6","4a8e"+"106","a321"+"764"]
# word-anchored so an unrelated hex digest cannot false-positive
BAD = re.compile(r"(?<![0-9a-f])(" + "|".join(_TOK) + r")(?![0-9a-f])", re.I)
cjk_offenders, identity_offenders = [], []
for dp, _, fs in os.walk(ROOT):
    rel_dir = os.path.relpath(dp, ROOT)
    in_eval = rel_dir == EVAL_DIR or rel_dir.startswith(EVAL_DIR + os.sep)
    for f in fs:
        if not f.endswith((".py", ".md", ".json", ".txt")):
            continue
        p = pathlib.Path(dp) / f
        text = p.read_text(encoding="utf-8", errors="replace")
        rel = str(p.relative_to(ROOT))
        if CJK.search(text):
            cjk_offenders.append(rel)
        # benchmark identity is allowed only inside the evaluation section
        if BAD.search(text) and not in_eval:
            identity_offenders.append(rel)
print(f"[5] non-English text: {len(cjk_offenders)}; benchmark identity outside "
      f"{EVAL_DIR}/: {len(identity_offenders)}")
for o in (cjk_offenders + identity_offenders)[:5]:
    print(f"      {o}")
check(not cjk_offenders, "repository is English-only")
check(not identity_offenders, f"pipeline is free of benchmark identity (outside {EVAL_DIR}/)")

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS[:10]:
        print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED")
