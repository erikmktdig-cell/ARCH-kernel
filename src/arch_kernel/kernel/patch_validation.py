"""Static scope and optimistic state preconditions for WP-K05 patches."""

from __future__ import annotations

from arch_kernel.contracts.patches import StatePatch
from arch_kernel.contracts.project_state import ProjectState
from arch_kernel.kernel.errors import ErrorCode, ErrorDetail, Severity
from arch_kernel.kernel.path_policy import validate_patch_path_policy


def _error(
    code: ErrorCode,
    message: str,
    *,
    path: tuple[str | int, ...],
    expected: str | int,
    actual: str | int,
    remediation_hint: str,
) -> ErrorDetail:
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


def collect_static_patch_errors(
    state: ProjectState,
    patch: StatePatch,
) -> tuple[ErrorDetail, ...]:
    """Collect operation policy errors first, followed by global preconditions."""

    errors: list[ErrorDetail] = []
    for index, operation in enumerate(patch.operations):
        path_error = validate_patch_path_policy(operation.path, operation.op)
        if path_error is not None:
            errors.append(
                path_error.model_copy(update={"path": ("operations", index, *path_error.path)})
            )

    if patch.project_id != state.metadata.project_id:
        errors.append(
            _error(
                ErrorCode.INVALID_REFERENCE,
                "Patch project_id does not match the ProjectState project.",
                path=("project_id",),
                expected=str(state.metadata.project_id),
                actual=str(patch.project_id),
                remediation_hint="Build the patch for the current project aggregate.",
            )
        )
    if patch.base_state_record_version != state.record_version:
        errors.append(
            _error(
                ErrorCode.STALE_STATE_VERSION,
                "Patch base_state_record_version is stale.",
                path=("base_state_record_version",),
                expected=state.record_version,
                actual=patch.base_state_record_version,
                remediation_hint="Reload ProjectState and rebuild the patch.",
            )
        )
    current_content_fingerprint = state.contract_content_fingerprint()
    if patch.base_state_content_fingerprint != current_content_fingerprint:
        errors.append(
            _error(
                ErrorCode.STALE_STATE_VERSION,
                "Patch base_state_content_fingerprint is stale.",
                path=("base_state_content_fingerprint",),
                expected=current_content_fingerprint,
                actual=patch.base_state_content_fingerprint,
                remediation_hint="Reload ProjectState and use its current content fingerprint.",
            )
        )
    return tuple(errors)


__all__ = ("collect_static_patch_errors",)
