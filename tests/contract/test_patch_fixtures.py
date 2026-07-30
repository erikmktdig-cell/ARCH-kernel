"""Contract tests for WP-K05 patch fixtures against the K03 base state."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import ExecutionStatus, StatePatch
from arch_kernel.kernel import ErrorCode, apply_state_patch_dry_run
from tests.patch_helpers import load_state

_ROOT = Path(__file__).parents[2] / "fixtures"
_VALID = _ROOT / "valid" / "state_patch"
_INVALID = _ROOT / "invalid" / "state_patch"


@pytest.mark.parametrize(
    "filename",
    [
        "replace_project_profile.json",
        "add_risk_record.json",
        "test_then_replace.json",
    ],
)
def test_valid_patch_fixtures_round_trip_and_complete(filename: str) -> None:
    state = load_state()
    state_patch = StatePatch.model_validate_json((_VALID / filename).read_text(encoding="utf-8"))

    restored = StatePatch.model_validate_json(state_patch.model_dump_json())
    result = apply_state_patch_dry_run(state, state_patch)

    assert restored == state_patch
    assert result.status is ExecutionStatus.COMPLETED
    assert result.projected_state is not None


@pytest.mark.parametrize(
    ("filename", "message"),
    [
        ("scope_insufficient.json", "declared scope"),
        ("invalid_path.json", "absolute non-empty canonical path"),
        ("scope_redundant.json", "covered by another"),
        ("duplicate_operation.json", "operations cannot contain duplicate"),
    ],
)
def test_structurally_invalid_patch_fixtures_are_rejected(
    filename: str,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        StatePatch.model_validate_json((_INVALID / filename).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("filename", "status", "code"),
    [
        (
            "stale_state_version.json",
            ExecutionStatus.CONFLICT_DETECTED,
            ErrorCode.STALE_STATE_VERSION,
        ),
        (
            "stale_state_fingerprint.json",
            ExecutionStatus.CONFLICT_DETECTED,
            ErrorCode.STALE_STATE_VERSION,
        ),
        (
            "add_existing.json",
            ExecutionStatus.CONFLICT_DETECTED,
            ErrorCode.INVALID_REFERENCE,
        ),
        (
            "replace_missing.json",
            ExecutionStatus.CONFLICT_DETECTED,
            ErrorCode.INVALID_REFERENCE,
        ),
        (
            "remove_required.json",
            ExecutionStatus.INVALID_INPUT,
            ErrorCode.IMMUTABLE_RECORD_MODIFICATION,
        ),
        (
            "invalid_target_value.json",
            ExecutionStatus.BLOCKED,
            ErrorCode.SCHEMA_VALIDATION_ERROR,
        ),
        (
            "registry_key_mismatch.json",
            ExecutionStatus.BLOCKED,
            ErrorCode.SCHEMA_VALIDATION_ERROR,
        ),
        (
            "stale_object_version.json",
            ExecutionStatus.CONFLICT_DETECTED,
            ErrorCode.STALE_OBJECT_VERSION,
        ),
    ],
)
def test_semantically_invalid_patch_fixtures_fail_as_documented(
    filename: str,
    status: ExecutionStatus,
    code: ErrorCode,
) -> None:
    state_patch = StatePatch.model_validate_json((_INVALID / filename).read_text(encoding="utf-8"))

    result = apply_state_patch_dry_run(load_state(), state_patch)

    assert result.status is status
    assert result.projected_state is None
    assert result.validation.errors[0].code is code
