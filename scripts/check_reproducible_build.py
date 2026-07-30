"""Build twice from clean copies and compare release artifacts."""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.release_common import (
    ReleaseCheckError,
    copy_release_source,
    expected_artifact_names,
    normalized_build_environment,
    run_command,
    semantic_archive_members,
    sha256_file,
)


def verify_reproducible_builds() -> dict[str, Any]:
    """Return structured evidence or raise on any mismatch."""

    builds: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="arch-kernel-repro-") as temp_name:
        temp = Path(temp_name)
        for index in (1, 2):
            source = temp / f"source-{index}"
            source.mkdir()
            copy_release_source(source)
            uv = shutil.which("uv")
            if uv is None:
                raise ReleaseCheckError("uv is required for reproducible build verification")
            run_command(
                (uv, "build", "--offline", "--out-dir", str(source / "dist")),
                cwd=source,
                env=normalized_build_environment(),
            )
            builds.append(source / "dist")
        differences: dict[str, list[str]] = {}
        hashes: dict[str, str] = {}
        for name in expected_artifact_names():
            first = builds[0] / name
            second = builds[1] / name
            first_hash = sha256_file(first)
            second_hash = sha256_file(second)
            hashes[name] = first_hash
            if first_hash != second_hash:
                first_members = semantic_archive_members(first)
                second_members = semantic_archive_members(second)
                member_names = sorted(set(first_members) | set(second_members))
                differences[name] = [
                    member
                    for member in member_names
                    if first_members.get(member) != second_members.get(member)
                ]
        if differences:
            raise ReleaseCheckError(f"reproducible build mismatch: {differences}")
        return {
            "source_date_epoch": normalized_build_environment()["SOURCE_DATE_EPOCH"],
            "hashes": hashes,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    try:
        evidence = verify_reproducible_builds()
    except ReleaseCheckError as error:
        print(f"FAIL: {error}")
        return 1
    print(f"PASS: byte-reproducible wheel and sdist ({evidence['source_date_epoch']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
