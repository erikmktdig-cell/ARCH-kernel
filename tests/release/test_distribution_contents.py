"""Direct wheel and sdist archive checks."""

from __future__ import annotations

from pathlib import Path

from scripts.release_common import inspect_distributions


def test_wheel_and_sdist_pass_direct_inspection(built_dist: Path) -> None:
    evidence = inspect_distributions(built_dist)
    assert evidence["members"]["wheel"] > 35
    assert evidence["members"]["sdist"] > 35
    assert evidence["artifacts"]["wheel"]["sha256"].startswith("sha256:")
    assert evidence["artifacts"]["sdist"]["sha256"].startswith("sha256:")
