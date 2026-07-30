"""Package metadata and version-surface checks."""

from __future__ import annotations

import importlib.metadata
import re

from scripts.release_common import ROOT, SUPPORTED_PYTHONS, package_version, project_metadata

import arch_kernel


def test_static_version_has_one_authoritative_source() -> None:
    metadata = project_metadata()
    assert metadata["dynamic"] == ["version"]
    assert "version" not in metadata
    assert package_version() == arch_kernel.__version__ == importlib.metadata.version("arch-kernel")
    assert (ROOT / "src" / "arch_kernel" / "__about__.py").read_text(encoding="utf-8").count(
        "__version__ ="
    ) == 1


def test_project_metadata_is_complete_and_real() -> None:
    metadata = project_metadata()
    assert metadata["name"] == "arch-kernel"
    assert metadata["readme"] == "README.md"
    assert metadata["requires-python"] == ">=3.12,<3.14"
    assert metadata["license"] == {"file": "LICENSE"}
    assert metadata["description"]
    assert metadata["keywords"]
    assert metadata["dependencies"] == ["pydantic>=2,<3"]
    assert "urls" not in metadata


def test_python_classifiers_match_supported_matrix() -> None:
    classifiers = project_metadata()["classifiers"]
    advertised = tuple(
        match.group(1)
        for classifier in classifiers
        if (match := re.fullmatch(r"Programming Language :: Python :: (3\.\d+)", classifier))
    )
    assert advertised == SUPPORTED_PYTHONS


def test_changelog_has_matching_release_heading() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{package_version()}]" in changelog
