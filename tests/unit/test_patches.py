"""Tests for immutable WP-K05 patch contracts."""

from typing import Any, cast

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import (
    DryRunResult,
    ExecutionStatus,
    PatchOperation,
    PatchOperationType,
    PatchPath,
    PatchValidationResult,
    StatePatch,
)
from tests.patch_helpers import operation, patch, replacement_profile


@pytest.mark.parametrize(
    "op",
    [PatchOperationType.ADD, PatchOperationType.REPLACE, PatchOperationType.TEST],
)
def test_value_operations_require_value(op: PatchOperationType) -> None:
    with pytest.raises(ValidationError, match="requires value"):
        PatchOperation(
            op=op,
            path=PatchPath.parse("/profile"),
        )


def test_remove_rejects_even_explicit_null_value() -> None:
    with pytest.raises(ValidationError, match="does not accept value"):
        PatchOperation(
            op=PatchOperationType.REMOVE,
            path=PatchPath.parse("/risks/RISK-01HZX7M3FQ1T2Q9V8Y6K4C2B1E"),
            value=None,
        )


def test_patch_operation_value_is_defensively_copied_and_deep_frozen() -> None:
    source: dict[str, Any] = {"nested": {"value": 1}, "items": ["first"]}
    item = operation(PatchOperationType.REPLACE, "/profile", value=source)
    frozen = cast(Any, item.value)

    source["nested"]["value"] = 2

    assert item.model_dump(mode="json")["value"]["nested"]["value"] == 1
    with pytest.raises(TypeError):
        frozen["nested"]["value"] = 3
    with pytest.raises(AttributeError):
        frozen["items"].append("second")


def test_state_patch_and_operations_are_frozen_and_round_trip() -> None:
    item = operation(
        PatchOperationType.REPLACE,
        "/profile",
        value=replacement_profile(),
    )
    state_patch = patch(item)
    mutable_patch = cast(Any, state_patch)
    mutable_operation = cast(Any, item)

    with pytest.raises(ValidationError, match="Instance is frozen"):
        mutable_patch.reason = "Changed"
    with pytest.raises(ValidationError, match="Instance is frozen"):
        mutable_operation.path = PatchPath.parse("/metadata")

    restored = StatePatch.model_validate_json(state_patch.model_dump_json())
    assert restored == state_patch
    assert isinstance(restored.model_dump(mode="json")["operations"][0]["value"], dict)


def test_state_patch_rejects_redundant_scope() -> None:
    item = operation(
        PatchOperationType.REPLACE,
        "/profile",
        value=replacement_profile(),
    )

    with pytest.raises(ValidationError, match="covered by another"):
        patch(item, scope=("/profile", "/profile/project_type"))


def test_state_patch_rejects_operation_outside_scope() -> None:
    item = operation(
        PatchOperationType.REPLACE,
        "/profile",
        value=replacement_profile(),
    )

    with pytest.raises(ValidationError, match="declared scope"):
        patch(item, scope=("/metadata",))


def test_state_patch_rejects_exact_duplicate_operations() -> None:
    item = operation(
        PatchOperationType.REPLACE,
        "/profile",
        value=replacement_profile(),
    )

    with pytest.raises(ValidationError, match="operations cannot contain duplicate"):
        patch(item, item)


@pytest.mark.parametrize(
    "value",
    [
        b"bytes",
        (1, 2),
        {1, 2},
        object(),
        float("nan"),
        float("inf"),
    ],
)
def test_patch_operation_rejects_non_json_values(value: object) -> None:
    with pytest.raises(ValidationError):
        PatchOperation.model_validate(
            {
                "op": PatchOperationType.REPLACE,
                "path": PatchPath.parse("/profile/project_type"),
                "value": value,
            }
        )


def test_dry_run_result_rejects_incoherent_success_shape() -> None:
    state_patch = patch(
        operation(PatchOperationType.TEST, "/profile/project_type", value="platform")
    )

    with pytest.raises(ValidationError, match="Only completed"):
        DryRunResult(
            status=ExecutionStatus.COMPLETED,
            patch_id=state_patch.patch_id,
            original_state_record_fingerprint="sha256:" + "a" * 64,
            original_state_content_fingerprint="sha256:" + "b" * 64,
            projected_state_record_fingerprint=None,
            projected_state_content_fingerprint=None,
            changed_paths=(),
            validation=PatchValidationResult(is_valid=True),
            projected_state=None,
        )
