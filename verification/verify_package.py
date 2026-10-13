"""Compile and import the package, check asset bindings, and run behavioral tests."""
from __future__ import annotations

import ast
import importlib
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    modules = list((ROOT / "assetforge").rglob("*.py"))
    if not modules:
        raise RuntimeError("no package modules found")
    for path in modules:
        ast.parse(path.read_text())
        name = str(path.relative_to(ROOT).with_suffix("")).replace("/", ".")
        importlib.import_module(name)
    from assetforge.pipeline.assets import AssetLibrary
    descriptions = AssetLibrary().describe()
    print(f"Compiled/imported {len(modules)} modules; verified {len(descriptions)} assets.", flush=True)
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                            cwd=ROOT, timeout=120)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
