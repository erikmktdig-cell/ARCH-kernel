"""Pure atomic application of declarative patches to detached ProjectState data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from pydantic import ValidationError

from arch_kernel.contracts.enums import ExecutionStatus
from arch_kernel.contracts.patches import (
    DryRunResult,
    PatchOperation,
    PatchOperationType,
    PatchPath,
    PatchValidationResult,
    StatePatch,
)
from arch_kernel.contracts.project_state import ProjectState
from arch_kernel.kernel.errors import ErrorCode, ErrorDetail, Severity
from arch_kernel.kernel.event_validation import thaw_json
from arch_kernel.kernel.fingerprints import canonicalize_json, compute_content_fingerprint
from arch_kernel.kernel.patch_validation import collect_static_patch_errors
from arch_kernel.kernel.time import ensure_utc

type JsonData = None | bool | int | float | str | list[JsonData] | dict[str, JsonData]

_ROOT_MAP = {
    "metadata": "metadata",
    "profile": "profile",
    "lifecycle": "lifecycle",
    "phases": "phase_execution_records",
    "artifacts": "artifact_registry",
    "requirements": "requirement_registry",
    "risks": "risk_registry",
    "dependencies": "dependency_graph",
    "workflows": "workflow_registry",
}
_REGISTRY_ROOTS = {"phases", "artifacts", "requirements", "risks", "workflows"}
_CONFLICT_CODES = {
    ErrorCode.STALE_STATE_VERSION,
    ErrorCode.STALE_OBJECT_VERSION,
    ErrorCode.PATCH_TEST_FAILED,
    ErrorCode.INVALID_REFERENCE,
}


@dataclass(frozen=True, slots=True)
class _Target:
    exists: bool
    value: JsonData
    parent: dict[str, JsonData] | list[JsonData] | None
    key: str | int | None
    anchor: JsonData


def _error(
    code: ErrorCode,
    message: str,
    *,
    operation_index: int | None = None,
    field: str = "path",
    expected: str | int | None = None,
    actual: str | int | None = None,
    remediation_hint: str | None = None,
) -> ErrorDetail:
    path: tuple[str | int, ...] = (field,)
    if operation_index is not None:
        path = ("operations", operation_index, field)
    return ErrorDetail(
        code=code,
        message=message,
        path=path,
        entity_type="state_patch",
        expected=expected,
        actual=actual,
        remediation_hint=remediation_hint,
        severity=Severity.ERROR,
    )


def _find_decision_index(decisions: list[JsonData], decision_id: str) -> int | None:
    for index, decision in enumerate(decisions):
        if isinstance(decision, dict) and decision.get("decision_id") == decision_id:
            return index
    return None


def _internal_segments(
    document: dict[str, JsonData],
    path: PatchPath,
) -> tuple[str | int, ...] | None:
    root, *rest = path.segments
    if root == "decisions":
        decisions = document.get("decision_log")
        if not isinstance(decisions, list):
            return None
        if not rest:
            return ("decision_log",)
        index = _find_decision_index(decisions, rest[0])
        if index is None:
            return None
        return ("decision_log", index, *rest[1:])
    internal_root = _ROOT_MAP[root]
    converted: list[str | int] = [internal_root]
    for index, segment in enumerate(rest):
        if root == "dependencies" and index == 0:
            converted.append(int(segment))
        else:
            converted.append(segment)
    return tuple(converted)


def _walk(document: dict[str, JsonData], segments: tuple[str | int, ...]) -> _Target:
    current: JsonData = document
    parent: dict[str, JsonData] | list[JsonData] | None = None
    key: str | int | None = None
    for segment in segments:
        parent = current if isinstance(current, (dict, list)) else None
        key = segment
        if isinstance(current, dict) and isinstance(segment, str):
            if segment not in current:
                return _Target(False, None, current, segment, None)
            current = current[segment]
        elif isinstance(current, list) and isinstance(segment, int):
            if segment < 0 or segment >= len(current):
                return _Target(False, None, current, segment, None)
            current = current[segment]
        else:
            return _Target(False, None, parent, key, None)
    return _Target(True, current, parent, key, current)


def _resolve_target(
    document: dict[str, JsonData],
    path: PatchPath,
    *,
    for_add: bool,
) -> _Target:
    if path.segments[0] == "decisions" and len(path.segments) >= 2:
        decisions = document.get("decision_log")
        if isinstance(decisions, list):
            index = _find_decision_index(decisions, path.segments[1])
            if index is None and for_add and len(path.segments) == 2:
                return _Target(False, None, decisions, len(decisions), None)
    segments = _internal_segments(document, path)
    if segments is None:
        return _Target(False, None, None, None, None)
    target = _walk(document, segments)
    if path.segments[0] in _REGISTRY_ROOTS and len(path.segments) >= 2:
        anchor = _walk(document, segments[:2])
        return _Target(target.exists, target.value, target.parent, target.key, anchor.value)
    if path.segments[0] == "decisions" and len(path.segments) >= 2:
        anchor = _walk(document, segments[:2])
        return _Target(target.exists, target.value, target.parent, target.key, anchor.value)
    if path.segments[0] in {"metadata", "profile", "lifecycle"}:
        anchor = _walk(document, segments[:1])
        return _Target(target.exists, target.value, target.parent, target.key, anchor.value)
    return target


def _check_object_preconditions(
    operation: PatchOperation,
    target: _Target,
    index: int,
) -> ErrorDetail | None:
    if operation.expected_record_version is not None:
        if not isinstance(target.anchor, dict):
            return _error(
                ErrorCode.STALE_OBJECT_VERSION,
                "expected_record_version requires a versioned record target.",
                operation_index=index,
                field="expected_record_version",
                expected=operation.expected_record_version,
                actual="record unavailable",
            )
        actual_version = target.anchor.get("record_version")
        if actual_version != operation.expected_record_version:
            return _error(
                ErrorCode.STALE_OBJECT_VERSION,
                "Patch expected_record_version is stale.",
                operation_index=index,
                field="expected_record_version",
                expected=operation.expected_record_version,
                actual=cast(int | str | None, actual_version),
                remediation_hint="Reload the target record before rebuilding the patch.",
            )
    if operation.expected_content_fingerprint is not None:
        if target.anchor is None:
            actual_fingerprint = "target unavailable"
        else:
            actual_fingerprint = compute_content_fingerprint(target.anchor)
        if actual_fingerprint != operation.expected_content_fingerprint:
            return _error(
                ErrorCode.STALE_OBJECT_VERSION,
                "Patch expected_content_fingerprint is stale.",
                operation_index=index,
                field="expected_content_fingerprint",
                expected=operation.expected_content_fingerprint,
                actual=actual_fingerprint,
                remediation_hint="Reload the target and use its current content fingerprint.",
            )
    return None


def _assign(target: _Target, value: JsonData) -> None:
    if isinstance(target.parent, dict) and isinstance(target.key, str):
        target.parent[target.key] = value
    elif isinstance(target.parent, list) and isinstance(target.key, int):
        if target.key == len(target.parent):
            target.parent.append(value)
        else:
            target.parent[target.key] = value
    else:  # pragma: no cover - guarded by operation checks
        raise AssertionError("Patch target has no assignable parent.")


def _remove(target: _Target) -> None:
    valid_mapping_target = isinstance(target.parent, dict) and isinstance(target.key, str)
    valid_sequence_target = isinstance(target.parent, list) and isinstance(target.key, int)
    if not (valid_mapping_target or valid_sequence_target):
        raise AssertionError("Patch target has no removable parent.")
    parent = cast(Any, target.parent)
    del parent[target.key]


def _operation_error(
    operation: PatchOperation,
    target: _Target,
    index: int,
) -> ErrorDetail | None:
    if (
        operation.op is PatchOperationType.ADD
        and isinstance(target.parent, list)
        and isinstance(target.key, int)
        and target.key > len(target.parent)
    ):
        return _error(
            ErrorCode.INVALID_REFERENCE,
            "add array index must equal the current array length.",
            operation_index=index,
            expected=len(target.parent),
            actual=target.key,
        )
    if operation.op is PatchOperationType.ADD and target.exists:
        return _error(
            ErrorCode.INVALID_REFERENCE,
            "add requires an absent target.",
            operation_index=index,
            expected="absent path",
            actual=str(operation.path),
        )
    if operation.op is not PatchOperationType.ADD and not target.exists:
        return _error(
            ErrorCode.INVALID_REFERENCE,
            f"{operation.op.value} requires an existing target.",
            operation_index=index,
            expected="existing path",
            actual=str(operation.path),
        )
    return _check_object_preconditions(operation, target, index)


def _apply_operations(
    document: dict[str, JsonData],
    patch: StatePatch,
) -> tuple[tuple[PatchPath, ...], tuple[tuple[str, str], ...], ErrorDetail | None]:
    changed_paths: list[PatchPath] = []
    touched_records: list[tuple[str, str]] = []
    for index, operation in enumerate(patch.operations):
        target = _resolve_target(
            document,
            operation.path,
            for_add=operation.op is PatchOperationType.ADD,
        )
        error = _operation_error(operation, target, index)
        if error is not None:
            return (), (), error
        expected_value = thaw_json(operation.value)
        if operation.op is PatchOperationType.TEST:
            if canonicalize_json(target.value) != canonicalize_json(expected_value):
                return (
                    (),
                    (),
                    _error(
                        ErrorCode.PATCH_TEST_FAILED,
                        "test operation did not match the canonical current value.",
                        operation_index=index,
                        field="value",
                        expected=canonicalize_json(expected_value).decode("utf-8"),
                        actual=canonicalize_json(target.value).decode("utf-8"),
                        remediation_hint="Reload the target value before rebuilding the patch.",
                    ),
                )
            continue
        if operation.op is PatchOperationType.REPLACE and canonicalize_json(
            target.value
        ) == canonicalize_json(expected_value):
            continue
        if operation.op in {PatchOperationType.ADD, PatchOperationType.REPLACE}:
            _assign(target, expected_value)
        else:
            _remove(target)
        if operation.path not in changed_paths:
            changed_paths.append(operation.path)
        if operation.path.segments[0] in _REGISTRY_ROOTS and len(operation.path.segments) >= 3:
            record_key = (operation.path.segments[0], operation.path.segments[1])
            if record_key not in touched_records:
                touched_records.append(record_key)
    return tuple(changed_paths), tuple(touched_records), None


def _touch_versioned_records(
    document: dict[str, JsonData],
    touched_records: tuple[tuple[str, str], ...],
    evaluated_at: datetime,
) -> None:
    timestamp = evaluated_at.isoformat().replace("+00:00", "Z")
    for public_root, record_id in touched_records:
        registry = document.get(_ROOT_MAP[public_root])
        if not isinstance(registry, dict):
            continue
        record = registry.get(record_id)
        if not isinstance(record, dict):
            continue
        record_version = record.get("record_version")
        if isinstance(record_version, int) and not isinstance(record_version, bool):
            record["record_version"] = record_version + 1
            record["updated_at"] = timestamp
            if public_root == "workflows":
                root_version = document.get("record_version")
                if isinstance(root_version, int) and not isinstance(root_version, bool):
                    record["state_version_updated"] = root_version + 1


def _validation(errors: tuple[ErrorDetail, ...]) -> PatchValidationResult:
    return PatchValidationResult(is_valid=not errors, errors=errors, warnings=())


def validate_state_patch(
    state: ProjectState,
    patch: StatePatch,
) -> PatchValidationResult:
    """Validate scope, optimistic preconditions, and ordered operations."""

    static_errors = collect_static_patch_errors(state, patch)
    if static_errors:
        return _validation(static_errors)
    document = cast(dict[str, JsonData], state.model_dump(mode="json"))
    _, _, operation_error = _apply_operations(document, patch)
    if operation_error is not None:
        return _validation((operation_error,))
    try:
        ProjectState.model_validate_json(canonicalize_json(document))
    except ValidationError as error:
        return _validation(
            (
                _error(
                    ErrorCode.SCHEMA_VALIDATION_ERROR,
                    "Patch operations produce an invalid ProjectState.",
                    field="projected_state",
                    expected="valid ProjectState",
                    actual=error.errors()[0]["type"],
                    remediation_hint="Correct the patch values or preserve aggregate references.",
                ),
            )
        )
    return _validation(())


def _failed_result(
    state: ProjectState,
    patch: StatePatch,
    validation: PatchValidationResult,
    *,
    blocked: bool = False,
) -> DryRunResult:
    status = ExecutionStatus.BLOCKED if blocked else ExecutionStatus.INVALID_INPUT
    if any(error.code in _CONFLICT_CODES for error in validation.errors):
        status = ExecutionStatus.CONFLICT_DETECTED
    return DryRunResult(
        status=status,
        patch_id=patch.patch_id,
        original_state_record_fingerprint=state.record_fingerprint(),
        original_state_content_fingerprint=state.contract_content_fingerprint(),
        projected_state_record_fingerprint=None,
        projected_state_content_fingerprint=None,
        changed_paths=(),
        validation=validation,
        projected_state=None,
    )


def apply_state_patch_dry_run(
    state: ProjectState,
    patch: StatePatch,
    *,
    evaluated_at: datetime | None = None,
) -> DryRunResult:
    """Atomically simulate a patch on detached data without persistence or events."""

    static_errors = collect_static_patch_errors(state, patch)
    if static_errors:
        return _failed_result(state, patch, _validation(static_errors))

    document = cast(dict[str, JsonData], state.model_dump(mode="json"))
    changed_paths, touched_records, operation_error = _apply_operations(document, patch)
    if operation_error is not None:
        return _failed_result(state, patch, _validation((operation_error,)))

    evaluation_time = ensure_utc(evaluated_at or patch.created_at)
    if changed_paths:
        _touch_versioned_records(document, touched_records, evaluation_time)
        document["record_version"] = state.record_version + 1
        document["updated_at"] = evaluation_time.isoformat().replace("+00:00", "Z")
    try:
        projected_state = ProjectState.model_validate_json(canonicalize_json(document))
    except ValidationError as error:
        validation = _validation(
            (
                _error(
                    ErrorCode.SCHEMA_VALIDATION_ERROR,
                    "Patch operations produce an invalid ProjectState.",
                    field="projected_state",
                    expected="valid ProjectState",
                    actual=error.errors()[0]["type"],
                    remediation_hint="Correct the patch values or preserve aggregate references.",
                ),
            )
        )
        return _failed_result(state, patch, validation, blocked=True)

    validation = _validation(())
    return DryRunResult(
        status=ExecutionStatus.COMPLETED,
        patch_id=patch.patch_id,
        original_state_record_fingerprint=state.record_fingerprint(),
        original_state_content_fingerprint=state.contract_content_fingerprint(),
        projected_state_record_fingerprint=projected_state.record_fingerprint(),
        projected_state_content_fingerprint=projected_state.contract_content_fingerprint(),
        changed_paths=changed_paths,
        validation=validation,
        projected_state=projected_state,
    )


__all__ = ("apply_state_patch_dry_run", "validate_state_patch")
