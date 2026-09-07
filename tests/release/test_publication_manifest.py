"""C04-K final publication-manifest checks."""

from __future__ import annotations

import pytest
from scripts.build_publication_manifest import publication_manifest
from scripts.release_common import C01_IMPLEMENTATION_BASELINE, ReleaseCheckError

COMMIT = "a" * 40
CI_URL = "https://github.com/erikmktdig-cell/ARCH-kernel/actions/runs/123"
ARTIFACTS = {
    "wheel": {"filename": "arch_kernel-0.2.0-py3-none-any.whl", "sha256": "sha256:x"},
    "sdist": {"filename": "arch_kernel-0.2.0.tar.gz", "sha256": "sha256:y"},
}


def test_publication_manifest_is_deterministic_and_complete() -> None:
    first = publication_manifest(
        source_commit=COMMIT,
        test_count=630,
        skip_count=0,
        branch_coverage=91.25,
        hosted_ci_url=CI_URL,
        artifacts=ARTIFACTS,
    )
    second = publication_manifest(
        source_commit=COMMIT,
        test_count=630,
        skip_count=0,
        branch_coverage=91.25,
        hosted_ci_url=CI_URL,
        artifacts=ARTIFACTS,
    )

    assert first == second
    assert first["package_version"] == "0.2.0"
    assert first["implementation_baseline"] == C01_IMPLEMENTATION_BASELINE
    assert first["project_state_contract_version"] == "2.0.0"
    assert first["migration"] == {
        "identity": "project.state_add_workflow_registry",
        "source_version": "1.0.0",
        "target_version": "2.0.0",
    }
    assert first["expected_artifacts"] == ARTIFACTS
    assert first["tag_peeled_commit"] == COMMIT
    assert first["hosted_ci"]["status"] == "PASS"
    assert first["governance"]["force_pushes"] == "BLOCKED"


@pytest.mark.parametrize(
    ("commit", "tests", "skips", "coverage", "ci_url"),
    [
        ("short", 630, 0, 91.0, CI_URL),
        (COMMIT, 0, 0, 91.0, CI_URL),
        (COMMIT, 630, -1, 91.0, CI_URL),
        (COMMIT, 630, 0, 89.99, CI_URL),
        (COMMIT, 630, 0, 91.0, "https://example.invalid/run"),
    ],
)
def test_publication_manifest_rejects_unverified_evidence(
    commit: str,
    tests: int,
    skips: int,
    coverage: float,
    ci_url: str,
) -> None:
    with pytest.raises(ReleaseCheckError):
        publication_manifest(
            source_commit=commit,
            test_count=tests,
            skip_count=skips,
            branch_coverage=coverage,
            hosted_ci_url=ci_url,
            artifacts=ARTIFACTS,
        )
