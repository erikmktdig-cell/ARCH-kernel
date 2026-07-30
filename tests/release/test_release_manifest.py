"""Stable manifest generation, freshness, and orchestration checks."""

from __future__ import annotations

import pytest
from scripts.check_release import (
    ReleaseStage,
    _dependency_audit,
    _freshness,
    release_stages,
    run_stages,
    validate_tag,
)
from scripts.release_common import (
    ROOT,
    CommandResult,
    ReleaseCheckError,
    canonical_json_bytes,
    package_version,
    stable_release_manifest,
)


def test_release_manifest_is_deterministic_and_fresh() -> None:
    first = stable_release_manifest()
    second = stable_release_manifest()
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert (ROOT / "release" / "manifest.json").read_bytes() == canonical_json_bytes(first)
    assert first["expected_artifacts"]["hashes"] == {"sdist": None, "wheel": None}
    assert first["source_commit"] is None


def test_all_generated_release_inputs_are_fresh() -> None:
    _freshness()


def test_release_stage_order_is_canonical() -> None:
    names = [stage.name for stage in release_stages()]
    assert names[:3] == ["ruff lint", "ruff format", "mypy"]
    assert names[-3:] == [
        "dependency license policy",
        "candidate evidence",
        "release governance",
    ]
    assert names.index("build") < names.index("metadata, archives, and installed wheel")
    assert names.index("reproducible build") < names.index("candidate evidence")


def test_stage_runner_fails_closed() -> None:
    observed: list[str] = []

    def fail() -> None:
        observed.append("failed")
        raise ReleaseCheckError("expected")

    stages = (
        ReleaseStage("first", lambda: observed.append("first")),
        ReleaseStage("failure", fail),
        ReleaseStage("never", lambda: observed.append("never")),
    )
    with pytest.raises(ReleaseCheckError, match="expected"):
        run_stages(stages)
    assert observed == ["first", "failed"]


def test_tag_must_exactly_match_version() -> None:
    validate_tag(f"v{package_version()}")
    for invalid in (package_version(), f"release-{package_version()}", "v0.0.0", ""):
        with pytest.raises(ReleaseCheckError):
            validate_tag(invalid)


def test_connected_dependency_audit_exports_uv_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []

    def record_command(command: tuple[str, ...], **_: object) -> CommandResult:
        commands.append(command)
        return CommandResult(command=command, returncode=0, stdout="", stderr="")

    monkeypatch.setenv("ARCH_KERNEL_NETWORK_AUDIT", "1")
    monkeypatch.setattr("scripts.check_release.run_command", record_command)

    _dependency_audit()

    assert commands[0] == ("uv", "lock", "--check", "--offline")
    assert commands[1][:7] == (
        "uv",
        "export",
        "--all-groups",
        "--frozen",
        "--no-emit-project",
        "--format",
        "requirements-txt",
    )
    assert commands[2][0:2] == ("pip-audit", "-r")
    assert commands[2][3:] == ("--disable-pip", "--progress-spinner", "off")
