"""Build stable release expectations or candidate evidence."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.release_common import (
    ROOT,
    inspect_distributions,
    stable_release_manifest,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "release" / "manifest.json",
    )
    parser.add_argument("--candidate-dist", type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--coverage", type=float)
    args = parser.parse_args()

    manifest = stable_release_manifest()
    if args.candidate_dist is not None:
        manifest["expected_artifacts"] = inspect_distributions(args.candidate_dist)["artifacts"]
        coverage = manifest["coverage"]
        assert isinstance(coverage, dict)
        coverage["observed_percent"] = args.coverage
        manifest["source_commit"] = args.source_commit
        manifest["environment"] = {
            "source_date_epoch": os.environ.get("SOURCE_DATE_EPOCH"),
        }
    write_json(args.output, manifest)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
