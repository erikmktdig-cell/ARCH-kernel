"""Installed-wheel isolation and package-data smoke checks."""

from __future__ import annotations

from pathlib import Path

from scripts.release_common import isolated_install_smoke


def test_wheel_installs_and_runs_outside_checkout(built_dist: Path) -> None:
    isolated_install_smoke(built_dist)
