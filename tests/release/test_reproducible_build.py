"""Clean-copy reproducible build gate."""

from __future__ import annotations

from scripts.check_reproducible_build import verify_reproducible_builds


def test_wheel_and_sdist_are_byte_reproducible() -> None:
    evidence = verify_reproducible_builds()
    assert len(evidence["hashes"]) == 2
