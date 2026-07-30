"""Tests for patch scope and optimistic precondition validation."""

from arch_kernel.contracts import (
    PatchOperationType,
    ProjectId,
)
from arch_kernel.kernel import ErrorCode, compute_content_fingerprint, validate_state_patch
from tests.patch_helpers import load_state, operation, patch, replacement_profile


def test_valid_patch_passes_validation() -> None:
    state = load_state()
    state_patch = patch(
        operation(
            PatchOperationType.REPLACE,
            "/profile",
            value=replacement_profile(state),
        ),
        state=state,
    )

    result = validate_state_patch(state, state_patch)

    assert result.is_valid
    assert result.errors == ()


def test_project_mismatch_is_rejected() -> None:
    state = load_state()
    state_patch = patch(
        operation(PatchOperationType.TEST, "/profile/project_type", value="platform"),
        state=state,
        project_id=ProjectId.from_str("PRJ-01HZX7M3FQ1T2Q9V8Y6K4C2B1M"),
    )

    result = validate_state_patch(state, state_patch)

    assert result.errors[0].code == ErrorCode.INVALID_REFERENCE


def test_stale_state_version_and_fingerprint_are_reported_deterministically() -> None:
    state = load_state()
    state_patch = patch(
        operation(PatchOperationType.TEST, "/profile/project_type", value="platform"),
        state=state,
        base_state_record_version=state.record_version + 1,
        base_state_content_fingerprint="sha256:" + "0" * 64,
    )

    result = validate_state_patch(state, state_patch)

    assert [error.code for error in result.errors] == [
        ErrorCode.STALE_STATE_VERSION,
        ErrorCode.STALE_STATE_VERSION,
    ]


def test_stale_object_record_version_is_rejected() -> None:
    state = load_state()
    artifact_id = next(iter(state.artifact_registry))
    state_patch = patch(
        operation(
            PatchOperationType.TEST,
            f"/artifacts/{artifact_id}",
            value=state.artifact_registry[artifact_id].model_dump(mode="json"),
            expected_record_version=2,
        ),
        state=state,
        scope=("/artifacts",),
    )

    result = validate_state_patch(state, state_patch)

    assert result.errors[0].code == ErrorCode.STALE_OBJECT_VERSION
    assert result.errors[0].actual == 1


def test_stale_object_content_fingerprint_is_rejected() -> None:
    state = load_state()
    artifact_id = next(iter(state.artifact_registry))
    artifact = state.artifact_registry[artifact_id]
    assert compute_content_fingerprint(artifact.canonical_dict()).startswith("sha256:")
    state_patch = patch(
        operation(
            PatchOperationType.TEST,
            f"/artifacts/{artifact_id}",
            value=artifact.model_dump(mode="json"),
            expected_content_fingerprint="sha256:" + "0" * 64,
        ),
        state=state,
        scope=("/artifacts",),
    )

    result = validate_state_patch(state, state_patch)

    assert result.errors[0].code == ErrorCode.STALE_OBJECT_VERSION


def test_path_policy_errors_precede_global_preconditions() -> None:
    state = load_state()
    state_patch = patch(
        operation(PatchOperationType.TEST, "/unknown/value", value=1),
        state=state,
        scope=("/unknown",),
        base_state_record_version=2,
    )

    result = validate_state_patch(state, state_patch)

    assert [error.code for error in result.errors] == [
        ErrorCode.PATCH_SCOPE_VIOLATION,
        ErrorCode.STALE_STATE_VERSION,
    ]
