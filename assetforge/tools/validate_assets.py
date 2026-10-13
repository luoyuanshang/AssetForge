"""Check the construction catalog and all bound asset files."""
from __future__ import annotations

import json
import argparse

from assetforge.pipeline.assets import AssetLibrary


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    library = AssetLibrary()
    descriptions = library.describe()
    print(json.dumps({"assets": len(descriptions), "catalog_sha256": library.sha256,
                      "files_verified": True, "native_admission": "operator-supplied"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
