"""Existing independent Reviewer with mandatory external construction validation."""
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))

# ``unified_benchmark_eval/.env`` is loaded with ``os.environ.setdefault`` and
# pins HTTP(S)_PROXY to a local 127.0.0.1:7900 helper.  When that helper is not
# running, every Reviewer prerequisite that needs the network -- the Bohrium
# sandbox CLI and the search tool -- fails with a connection error, which is
# then mis-recorded as an operational review failure.  Bind the variables to
# empty *before* the factory imports the author runtime so setdefault cannot re-introduce a
# dead proxy; an explicitly configured proxy is still honoured.
for _name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    _value = os.environ.get(_name, "")
    if not _value or "127.0.0.1" in _value or "localhost" in _value:
        os.environ[_name] = ""

from assetforge.pipeline.construction_review import install
if __name__=='__main__':raise SystemExit(install().main())
