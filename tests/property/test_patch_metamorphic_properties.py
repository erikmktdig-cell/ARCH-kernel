"""Metamorphic properties for the K05 patch engine."""

from __future__ import annotations

from arch_kernel.contracts import PatchOperationType
from arch_kernel.kernel import apply_state_patch_dry_run
from tests.patch_helpers import load_state, operation, patch


def test_test_only_patch_is_observational_identity() -> None:
    state = load_state()
    state_patch = patch(
        operation(
            PatchOperationType.TEST,
            "/profile/project_type",
            value=state.profile.project_type,
        ),
        state=state,
    )

    result = apply_state_patch_dry_run(state, state_patch)

    assert result.projected_state == state
    assert result.changed_paths == ()
    assert result.projected_state_content_fingerprint == (state.contract_content_fingerprint())


def test_disjoint_effective_replaces_commute() -> None:
    state = load_state()
    project_type = operation(
        PatchOperationType.REPLACE,
        "/profile/project_type",
        value="service",
    )
    criticality = operation(
        PatchOperationType.REPLACE,
        "/profile/criticality",
        value="low",
    )

    left = apply_state_patch_dry_run(
        state,
        patch(project_type, criticality, state=state),
    )
    right = apply_state_patch_dry_run(
        state,
        patch(criticality, project_type, state=state),
    )

    assert left.projected_state is not None
    assert right.projected_state is not None
    assert left.projected_state == right.projected_state
    assert set(left.changed_paths) == set(right.changed_paths)


def test_failed_dependent_operation_preserves_atomicity() -> None:
    state = load_state()
    original = state.model_dump_json()
    state_patch = patch(
        operation(PatchOperationType.REMOVE, "/profile/missing"),
        state=state,
    )

    result = apply_state_patch_dry_run(state, state_patch)

    assert result.projected_state is None
    assert result.changed_paths == ()
    assert state.model_dump_json() == original
