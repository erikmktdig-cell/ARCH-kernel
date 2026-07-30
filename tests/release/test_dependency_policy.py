"""Dependency lock and vulnerability-policy parsing tests."""

from __future__ import annotations

import tomllib
from typing import Any

import pytest
from scripts.release_common import ROOT, run_command


def test_lockfile_is_current_offline() -> None:
    run_command(("uv", "lock", "--check", "--offline"))


def test_lock_python_range_matches_project() -> None:
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert project["requires-python"] == ">=3.12,<3.14"
    assert 'requires-python = ">=3.12, <3.14"' in lock


@pytest.mark.parametrize(
    ("payload", "blocking"),
    [
        ({"dependencies": [], "fixes": []}, False),
        ({"dependencies": [{"name": "demo", "vulns": [{"id": "CVE-X"}]}]}, True),
    ],
)
def test_vulnerability_policy_result_parsing(payload: dict[str, Any], blocking: bool) -> None:
    vulnerabilities = [
        vulnerability
        for dependency in payload.get("dependencies", [])
        for vulnerability in dependency.get("vulns", [])
    ]
    assert bool(vulnerabilities) is blocking
