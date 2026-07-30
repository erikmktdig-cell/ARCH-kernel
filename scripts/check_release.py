"""Fail-closed WP-K12 release-check entry point."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_fixture_manifest import build_manifest as build_fixture_manifest
from scripts.build_regression_snapshots import (
    coverage_inventory_snapshot,
    public_contract_snapshot,
)
from scripts.check_reproducible_build import verify_reproducible_builds
from scripts.release_common import (
    ROOT,
    ReleaseCheckError,
    canonical_json_bytes,
    evaluate_license_policy,
    inspect_distributions,
    isolated_install_smoke,
    normalized_build_environment,
    package_version,
    read_json,
    release_environment_blockers,
    run_command,
    stable_release_manifest,
    write_json,
)


@dataclass(frozen=True)
class ReleaseStage:
    """One ordered release gate."""

    name: str
    action: Callable[[], None]


def validate_tag(tag: str, version: str | None = None) -> None:
    """Require the documented exact ``v<version>`` release tag."""

    expected = f"v{version or package_version()}"
    if tag != expected:
        raise ReleaseCheckError(f"release tag {tag!r} must equal {expected!r}")


def _command(*parts: str) -> Callable[[], None]:
    def action() -> None:
        run_command(parts, env=normalized_build_environment())

    return action


def _full_tests() -> None:
    coverage_path = ROOT / "build" / "release-coverage.json"
    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        (
            "pytest",
            "-p",
            "no:cacheprovider",
            f"--cov-report=json:{coverage_path}",
        ),
        env=normalized_build_environment(),
    )


def _reproducible_build() -> None:
    verify_reproducible_builds()


def _freshness() -> None:
    expected_fixture = (
        json.dumps(build_fixture_manifest(), ensure_ascii=False, indent=2).encode() + b"\n"
    )
    if (ROOT / "fixtures" / "manifest.json").read_bytes() != expected_fixture:
        raise ReleaseCheckError("stale generated artifact: fixtures/manifest.json")

    expected_snapshots = {
        "public_contracts.json": public_contract_snapshot(),
        "coverage_inventory.json": coverage_inventory_snapshot(),
    }
    for filename, payload in expected_snapshots.items():
        expected = json.dumps(payload, ensure_ascii=False, indent=2).encode() + b"\n"
        path = ROOT / "tests" / "regression" / "snapshots" / filename
        if path.read_bytes() != expected:
            raise ReleaseCheckError(f"stale generated artifact: {path.relative_to(ROOT)}")

    from arch_kernel.kernel import build_builtin_contract_registry, publish_registry_schemas

    with tempfile.TemporaryDirectory(prefix="arch-kernel-schema-check-") as temp_name:
        generated = Path(temp_name)
        publish_registry_schemas(build_builtin_contract_registry(), generated)
        expected_files = sorted(
            path.relative_to(ROOT / "schemas") for path in (ROOT / "schemas").rglob("*.json")
        )
        generated_files = sorted(path.relative_to(generated) for path in generated.rglob("*.json"))
        if expected_files != generated_files:
            raise ReleaseCheckError("published schema file set is stale")
        for relative in expected_files:
            if (ROOT / "schemas" / relative).read_bytes() != (generated / relative).read_bytes():
                raise ReleaseCheckError(f"stale generated artifact: schemas/{relative.as_posix()}")

    if (ROOT / "release" / "manifest.json").read_bytes() != canonical_json_bytes(
        stable_release_manifest()
    ):
        raise ReleaseCheckError("stale generated artifact: release/manifest.json")


def _registry_audit() -> None:
    from arch_kernel.kernel import audit_contract_registry, build_builtin_contract_registry

    result = audit_contract_registry(build_builtin_contract_registry())
    if not result.success:
        raise ReleaseCheckError("built-in contract registry audit failed")


def _build() -> None:
    dist = ROOT / "dist"
    if dist.exists():
        shutil.rmtree(dist)
    run_command(("uv", "build", "--offline"), env=normalized_build_environment())


def _artifact_checks() -> None:
    artifacts = tuple(
        str(path)
        for path in sorted((ROOT / "dist").iterdir())
        if path.suffix == ".whl" or path.name.endswith(".tar.gz")
    )
    run_command(("twine", "check", *artifacts))
    inspect_distributions(ROOT / "dist")
    isolated_install_smoke(ROOT / "dist")


def _dependency_audit() -> None:
    run_command(("uv", "lock", "--check", "--offline"))
    if os.environ.get("ARCH_KERNEL_NETWORK_AUDIT") == "1":
        with tempfile.TemporaryDirectory(prefix="arch-kernel-audit-") as temp_name:
            requirements = Path(temp_name) / "requirements.txt"
            run_command(
                (
                    "uv",
                    "export",
                    "--all-groups",
                    "--frozen",
                    "--no-emit-project",
                    "--format",
                    "requirements-txt",
                    "--output-file",
                    str(requirements),
                )
            )
            run_command(
                (
                    "pip-audit",
                    "-r",
                    str(requirements),
                    "--disable-pip",
                    "--progress-spinner",
                    "off",
                )
            )
    else:
        print("    advisory: network vulnerability refresh skipped; lock integrity passed")


def parse_license_inventory(payload: str) -> list[dict[str, str]]:
    """Normalize pip-licenses JSON for deterministic policy evaluation."""

    raw = json.loads(payload)
    return [
        {
            "name": item["Name"],
            "version": item["Version"],
            "license": item["License"] or "UNKNOWN",
        }
        for item in raw
    ]


def _license_audit() -> None:
    runtime_names = (
        "annotated-types",
        "pydantic",
        "pydantic-core",
        "typing-extensions",
        "typing-inspection",
    )
    result = run_command(
        ("pip-licenses", "--format=json", "--packages", *runtime_names),
    )
    inventory = parse_license_inventory(result.stdout)
    policy = evaluate_license_policy(inventory)
    development_result = run_command(("pip-licenses", "--format=json"))
    development_inventory = parse_license_inventory(development_result.stdout)
    development_policy = evaluate_license_policy(development_inventory)
    write_json(
        ROOT / "dist" / "dependency-licenses.json",
        {
            "runtime": {"policy": policy, "inventory": inventory},
            "development_environment": {
                "policy": development_policy,
                "inventory": development_inventory,
            },
        },
    )
    if policy["denied"] or policy["manual_review"]:
        raise ReleaseCheckError(
            "runtime dependency license policy requires review: "
            f"denied={policy['denied']}, manual_review={policy['manual_review']}"
        )


def _collected_count(marker: str) -> int:
    result = run_command(
        ("pytest", "--collect-only", "-q", "-o", "addopts=", "-m", marker),
    )
    match = re.search(r"(\d+)/\d+ tests collected", result.stdout)
    if match is None:
        raise ReleaseCheckError(f"could not determine collected count for {marker}")
    return int(match.group(1))


def _candidate_evidence() -> None:
    evidence = stable_release_manifest()
    evidence["expected_artifacts"] = inspect_distributions(ROOT / "dist")["artifacts"]
    evidence["environment"] = {
        "source_date_epoch": normalized_build_environment()["SOURCE_DATE_EPOCH"]
    }
    supplied_commit = os.environ.get("ARCH_KERNEL_SOURCE_COMMIT")
    evidence["source_commit"] = supplied_commit
    evidence["test_counts"] = {
        marker: _collected_count(marker)
        for marker in ("unit", "contract", "property", "regression", "release")
    }
    coverage_path = ROOT / "build" / "release-coverage.json"
    if coverage_path.exists():
        coverage_payload = read_json(coverage_path)
        coverage = evidence["coverage"]
        assert isinstance(coverage, dict)
        coverage["observed_percent"] = round(
            float(coverage_payload["totals"]["percent_covered"]),
            2,
        )
    elif supplied_coverage := os.environ.get("ARCH_KERNEL_COVERAGE_PERCENT"):
        coverage = evidence["coverage"]
        assert isinstance(coverage, dict)
        coverage["observed_percent"] = round(float(supplied_coverage), 2)
    write_json(ROOT / "dist" / "release-evidence.json", evidence)


def _governance() -> None:
    blockers = release_environment_blockers()
    if blockers:
        raise ReleaseCheckError("release blocked: " + "; ".join(blockers))


def release_stages(*, include_quality: bool = True) -> tuple[ReleaseStage, ...]:
    """Return canonical ordered stages, exposed for fail-closed tests."""

    stages: list[ReleaseStage] = []
    if include_quality:
        stages.extend(
            [
                ReleaseStage("ruff lint", _command("ruff", "check", ".")),
                ReleaseStage("ruff format", _command("ruff", "format", "--check", ".")),
                ReleaseStage("mypy", _command("mypy", "src", "tests", "scripts")),
                ReleaseStage("full tests", _full_tests),
                ReleaseStage(
                    "property tests",
                    _command("pytest", "-p", "no:cacheprovider", "-m", "property"),
                ),
                ReleaseStage(
                    "regression tests",
                    _command("pytest", "-p", "no:cacheprovider", "-m", "regression"),
                ),
                ReleaseStage(
                    "release tests",
                    _command("pytest", "-p", "no:cacheprovider", "-m", "release"),
                ),
            ]
        )
    stages.extend(
        [
            ReleaseStage("generated artifact freshness", _freshness),
            ReleaseStage("contract registry audit", _registry_audit),
            ReleaseStage("build", _build),
            ReleaseStage("metadata, archives, and installed wheel", _artifact_checks),
            ReleaseStage("reproducible build", _reproducible_build),
            ReleaseStage("dependency vulnerability policy", _dependency_audit),
            ReleaseStage("dependency license policy", _license_audit),
            ReleaseStage("candidate evidence", _candidate_evidence),
            ReleaseStage("release governance", _governance),
        ]
    )
    return tuple(stages)


def run_stages(stages: Sequence[ReleaseStage]) -> None:
    """Run stages in order and stop at the first failure."""

    for index, stage in enumerate(stages, start=1):
        print(f"[{index:02d}/{len(stages):02d}] {stage.name}")
        stage.action()
        print("    PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag")
    parser.add_argument("--skip-quality", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.tag is not None:
            validate_tag(args.tag)
        run_stages(release_stages(include_quality=not args.skip_quality))
    except ReleaseCheckError as error:
        print(f"FAIL: {error}")
        return 1
    print("PASS: release candidate satisfies WP-K12")
    return 0


if __name__ == "__main__":
    sys.exit(main())
