"""Validate built distributions and their installed behavior."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.release_common import (
    ROOT,
    ReleaseCheckError,
    inspect_distributions,
    isolated_install_smoke,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist", nargs="?", type=Path, default=ROOT / "dist")
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    try:
        evidence = inspect_distributions(args.dist)
        if not args.skip_smoke:
            isolated_install_smoke(args.dist)
            evidence["installed_package_smoke"] = "passed"
        if args.evidence is not None:
            write_json(args.evidence, evidence)
    except ReleaseCheckError as error:
        print(f"FAIL: {error}")
        return 1
    print("PASS: wheel, sdist, metadata, archive safety, package data, and installed smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
