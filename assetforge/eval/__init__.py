"""Convenience wrapper so the evaluation driver can be invoked as a module.

The driver itself lives in ``evaluation/`` at the repository root, because it is a
standalone pipeline rather than part of the pipeline package. This wrapper simply locates and
runs it, so ``python -m assetforge.eval`` works from an installed copy too.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None):
    driver = ROOT / "evaluation" / "run_evaluation.py"
    if not driver.exists():
        raise SystemExit("the evaluation driver is not present in this checkout")
    sys.argv = [str(driver)] + list(argv if argv is not None else sys.argv[1:])
    runpy.run_path(str(driver), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
