"""Tests for pure atomic StatePatch dry runs."""

from datetime import timedelta

from arch_kernel.contracts import ExecutionStatus, PatchOperationType
from arch_kernel.kernel import ErrorCode, apply_state_patch_dry_run
from tests.patch_helpers import (
    PATCH_TIME,
    load_state,
    new_risk_payload,
    operation,
    patch,
    replacement_profile,
)


def test_replace_profile_succeeds_without_mutating_original() -> None:
    state = load_state()
    before = state.canonical_json()
    state_patch = patch(
        operation(
            PatchOperationType.REPLACE,
            "/profile",
            value=replacement_profile(state),
        ),
        state=state,
    )

    result = apply_state_patch_dry_run(
        state,
        state_patch,
        evaluated_at=PATCH_TIME + timedelta(minutes=1),
    )

    assert result.status is ExecutionStatus.COMPLETED
    assert result.projected_state is not None
    assert result.projected_state.profile.project_type == "service"
    assert result.projected_state.record_version == state.record_version + 1
    assert result.projected_state.created_at == state.created_at
    assert result.projected_state.updated_at == PATCH_TIME + timedelta(minutes=1)
    assert state.canonical_json() == before
    assert result.projected_state_record_fingerprint == result.projected_state.record_fingerprint()
    assert (
        result.projected_state_content_fingerprint
        == result.projected_state.contract_content_fingerprint()
    )
    assert result.changed_paths == (state_patch.operations[0].path,)


def test_add_risk_record_succeeds_and_add_existing_conflicts() -> None:
    state = load_state()
    add = operation(
        PatchOperationType.ADD,
        "/risks/RISK-01HZX7M3FQ1T2Q9V8Y6K4C2B1J",
        value=new_risk_payload(),
    )
    success = apply_state_patch_dry_run(
        state,
        patch(add, state=state, scope=("/risks",)),
    )

    assert success.status is ExecutionStatus.COMPLETED
    assert success.projected_state is not None
    assert len(success.projected_state.risk_registry) == len(state.risk_registry) + 1

    existing_id = next(iter(state.risk_registry))
    conflict = apply_state_patch_dry_run(
        state,
        patch(
            operation(
                PatchOperationType.ADD,
                f"/risks/{existing_id}",
                value=state.risk_registry[existing_id].model_dump(mode="json"),
            ),
            state=state,
            scope=("/risks",),
        ),
    )
    assert conflict.status is ExecutionStatus.CONFLICT_DETECTED
    assert conflict.projected_state is None


def test_replace_missing_and_test_failure_are_conflicts() -> None:
    state = load_state()
    missing = patch(
        operation(
            PatchOperationType.REPLACE,
            "/risks/RISK-01HZX7M3FQ1T2Q9V8Y6K4C2B1J",
            value=new_risk_payload(),
        ),
        state=state,
        scope=("/risks",),
    )
    failed_test = patch(
        operation(PatchOperationType.TEST, "/profile/project_type", value="wrong"),
        state=state,
    )

    assert apply_state_patch_dry_run(state, missing).status is ExecutionStatus.CONFLICT_DETECTED
    test_result = apply_state_patch_dry_run(state, failed_test)
    assert test_result.status is ExecutionStatus.CONFLICT_DETECTED
    assert test_result.validation.errors[0].code == ErrorCode.PATCH_TEST_FAILED


def test_remove_risk_succeeds_but_remove_required_section_is_invalid() -> None:
    state = load_state()
    risk_id = next(iter(state.risk_registry))
    remove_risk = patch(
        operation(PatchOperationType.REMOVE, f"/risks/{risk_id}"),
        state=state,
        scope=("/risks",),
    )
    remove_metadata = patch(
        operation(PatchOperationType.REMOVE, "/metadata"),
        state=state,
        scope=("/metadata",),
    )

    success = apply_state_patch_dry_run(state, remove_risk)
    invalid = apply_state_patch_dry_run(state, remove_metadata)

    assert success.status is ExecutionStatus.COMPLETED
    assert success.projected_state is not None
    assert risk_id not in success.projected_state.risk_registry
    assert invalid.status is ExecutionStatus.INVALID_INPUT
    assert invalid.projected_state is None
    assert invalid.validation.errors[0].code == ErrorCode.IMMUTABLE_RECORD_MODIFICATION


def test_test_then_replace_is_ordered_and_atomic() -> None:
    state = load_state()
    state_patch = patch(
        operation(PatchOperationType.TEST, "/profile/project_type", value="platform"),
        operation(PatchOperationType.REPLACE, "/profile/project_type", value="service"),
        state=state,
    )

    result = apply_state_patch_dry_run(state, state_patch)

    assert result.status is ExecutionStatus.COMPLETED
    assert result.projected_state is not None
    assert result.projected_state.profile.project_type == "service"
    assert result.changed_paths == (state_patch.operations[1].path,)


def test_operation_failure_is_atomic_and_returns_no_projected_state() -> None:
    state = load_state()
    state_patch = patch(
        operation(
            PatchOperationType.ADD,
            "/risks/RISK-01HZX7M3FQ1T2Q9V8Y6K4C2B1J",
            value=new_risk_payload(),
        ),
        operation(
            PatchOperationType.REPLACE,
            "/risks/RISK-01HZX7M3FQ1T2Q9V8Y6K4C2B1N",
            value=new_risk_payload(),
        ),
        state=state,
        scope=("/risks",),
    )

    result = apply_state_patch_dry_run(state, state_patch)

    assert result.status is ExecutionStatus.CONFLICT_DETECTED
    assert result.projected_state is None
    assert result.changed_paths == ()
    assert len(state.risk_registry) == 1


def test_formally_valid_patch_that_breaks_references_is_blocked() -> None:
    state = load_state()
    artifact_id = next(iter(state.artifact_registry))
    state_patch = patch(
        operation(PatchOperationType.REMOVE, f"/artifacts/{artifact_id}"),
        state=state,
        scope=("/artifacts",),
    )

    result = apply_state_patch_dry_run(state, state_patch)

    assert result.status is ExecutionStatus.BLOCKED
    assert result.projected_state is None
    assert result.projected_state_record_fingerprint is None


def test_test_only_patch_preserves_versions_timestamps_and_fingerprints() -> None:
    state = load_state()
    state_patch = patch(
        operation(PatchOperationType.TEST, "/profile/project_type", value="platform"),
        state=state,
    )

    result = apply_state_patch_dry_run(state, state_patch)

    assert result.status is ExecutionStatus.COMPLETED
    assert result.changed_paths == ()
    assert result.projected_state is not None
    assert result.projected_state.record_version == state.record_version
    assert result.projected_state.updated_at == state.updated_at
    assert result.projected_state.record_fingerprint() == state.record_fingerprint()
    assert (
        result.projected_state.contract_content_fingerprint()
        == state.contract_content_fingerprint()
    )


def test_internal_record_mutation_increments_object_and_root_once() -> None:
    state = load_state()
    artifact_id = next(iter(state.artifact_registry))
    state_patch = patch(
        operation(
            PatchOperationType.REPLACE,
            f"/artifacts/{artifact_id}/name",
            value="Updated state model",
        ),
        state=state,
        scope=("/artifacts",),
    )
    evaluated_at = PATCH_TIME + timedelta(minutes=3)

    result = apply_state_patch_dry_run(state, state_patch, evaluated_at=evaluated_at)

    assert result.status is ExecutionStatus.COMPLETED
    assert result.projected_state is not None
    projected_artifact = result.projected_state.artifact_registry[artifact_id]
    assert result.projected_state.record_version == state.record_version + 1
    assert (
        projected_artifact.record_version == state.artifact_registry[artifact_id].record_version + 1
    )
    assert projected_artifact.updated_at == evaluated_at


def test_two_mutations_touch_same_record_only_once() -> None:
    state = load_state()
    artifact_id = next(iter(state.artifact_registry))
    state_patch = patch(
        operation(
            PatchOperationType.REPLACE,
            f"/artifacts/{artifact_id}/name",
            value="Updated state model",
        ),
        operation(
            PatchOperationType.REPLACE,
            f"/artifacts/{artifact_id}/owner",
            value="architecture-team",
        ),
        state=state,
        scope=("/artifacts",),
    )

    result = apply_state_patch_dry_run(state, state_patch)

    assert result.projected_state is not None
    projected = result.projected_state.artifact_registry[artifact_id]
    assert projected.record_version == state.artifact_registry[artifact_id].record_version + 1
    assert result.projected_state.record_version == state.record_version + 1


def test_mutations_on_two_records_touch_each_once() -> None:
    state = load_state()
    artifact_id = next(iter(state.artifact_registry))
    risk_id = next(iter(state.risk_registry))
    state_patch = patch(
        operation(
            PatchOperationType.REPLACE,
            f"/artifacts/{artifact_id}/name",
            value="Updated state model",
        ),
        operation(
            PatchOperationType.REPLACE,
            f"/risks/{risk_id}/title",
            value="Updated schema drift",
        ),
        state=state,
        scope=("/artifacts", "/risks"),
    )

    result = apply_state_patch_dry_run(state, state_patch)

    assert result.projected_state is not None
    assert (
        result.projected_state.artifact_registry[artifact_id].record_version
        == state.artifact_registry[artifact_id].record_version + 1
    )
    assert (
        result.projected_state.risk_registry[risk_id].record_version
        == state.risk_registry[risk_id].record_version + 1
    )
    assert result.projected_state.record_version == state.record_version + 1


def test_failed_patch_does_not_increment_any_record_version() -> None:
    state = load_state()
    artifact_id = next(iter(state.artifact_registry))
    state_patch = patch(
        operation(
            PatchOperationType.REPLACE,
            f"/artifacts/{artifact_id}/name",
            value="This mutation must be discarded",
        ),
        operation(
            PatchOperationType.REPLACE,
            "/risks/RISK-01HZX7M3FQ1T2Q9V8Y6K4C2B1J/title",
            value="Missing",
        ),
        state=state,
        scope=("/artifacts", "/risks"),
    )

    result = apply_state_patch_dry_run(state, state_patch)

    assert result.status is ExecutionStatus.CONFLICT_DETECTED
    assert result.projected_state is None
    assert state.record_version == 1
    assert state.artifact_registry[artifact_id].record_version == 1


def test_old_object_version_precondition_fails_after_record_mutation() -> None:
    state = load_state()
    artifact_id = next(iter(state.artifact_registry))
    first_patch = patch(
        operation(
            PatchOperationType.REPLACE,
            f"/artifacts/{artifact_id}/name",
            value="Version two",
            expected_record_version=1,
        ),
        state=state,
        scope=("/artifacts",),
    )
    first_result = apply_state_patch_dry_run(state, first_patch)
    assert first_result.projected_state is not None
    updated_state = first_result.projected_state
    stale_patch = patch(
        operation(
            PatchOperationType.REPLACE,
            f"/artifacts/{artifact_id}/name",
            value="Stale update",
            expected_record_version=1,
        ),
        state=updated_state,
        scope=("/artifacts",),
    )

    stale_result = apply_state_patch_dry_run(updated_state, stale_patch)

    assert stale_result.status is ExecutionStatus.CONFLICT_DETECTED
    assert stale_result.validation.errors[0].code == ErrorCode.STALE_OBJECT_VERSION


def test_canonically_identical_replace_is_a_no_op() -> None:
    state = load_state()
    state_patch = patch(
        operation(
            PatchOperationType.REPLACE,
            "/profile/project_type",
            value=state.profile.project_type,
        ),
        state=state,
    )

    result = apply_state_patch_dry_run(state, state_patch)

    assert result.projected_state is not None
    assert result.changed_paths == ()
    assert result.projected_state.record_fingerprint() == state.record_fingerprint()


def test_dependency_add_rejects_index_beyond_append_position() -> None:
    state = load_state()
    state_patch = patch(
        operation(PatchOperationType.ADD, "/dependencies/99", value={}),
        state=state,
        scope=("/dependencies",),
    )

    result = apply_state_patch_dry_run(state, state_patch)

    assert result.status is ExecutionStatus.CONFLICT_DETECTED
    assert result.validation.errors[0].code == ErrorCode.INVALID_REFERENCE
