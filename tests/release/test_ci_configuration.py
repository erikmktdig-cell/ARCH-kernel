"""GitHub Actions least-privilege and compatibility checks."""

from __future__ import annotations

import re

from scripts.release_common import ROOT, SUPPORTED_PYTHONS


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_ci_permissions_matrix_and_visible_suites() -> None:
    workflow = _workflow("ci.yml")
    assert re.search(r"permissions:\s+contents: read", workflow)
    assert "cancel-in-progress: true" in workflow
    assert 'python: ["3.12", "3.13"]' in workflow
    for version in (SUPPORTED_PYTHONS[0], SUPPORTED_PYTHONS[-1]):
        assert version in workflow
    assert "ubuntu-latest" in workflow
    assert "windows-latest" in workflow
    assert "-m property" in workflow
    assert "-m regression" in workflow
    assert "secrets." not in workflow
    assert "uv.lock" in workflow
    assert "uv sync --frozen --all-groups --python ${{ matrix.python }}" in workflow


def test_ci_actions_are_version_pinned() -> None:
    for filename in ("ci.yml", "release-check.yml"):
        for action in re.findall(r"uses:\s+([^\s]+)", _workflow(filename)):
            assert re.fullmatch(r"[^@]+@v\d+(?:\.\d+\.\d+)?", action), action


def test_release_workflow_is_non_publishing_and_tag_checked() -> None:
    workflow = _workflow("release-check.yml")
    assert '"v*"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "contents: read" in workflow
    assert "check_release.py --tag" in workflow
    assert "upload-artifact" in workflow
    assert "pypi" not in workflow.casefold()
    assert "release create" not in workflow.casefold()


def test_repository_forces_canonical_lf_checkouts() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in attributes.splitlines()
