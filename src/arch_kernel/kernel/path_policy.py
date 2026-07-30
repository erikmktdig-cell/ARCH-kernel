"""Conservative public path policy for WP-K05 state patches."""

from __future__ import annotations

from arch_kernel.contracts.ids import (
    ArtifactId,
    DecisionId,
    PhaseId,
    RequirementId,
    RiskId,
)
from arch_kernel.contracts.patches import PatchOperationType, PatchPath
from arch_kernel.kernel.errors import ErrorCode, ErrorDetail, Severity

_ROOTS = {
    "metadata",
    "profile",
    "lifecycle",
    "phases",
    "artifacts",
    "requirements",
    "decisions",
    "risks",
    "dependencies",
}
_REQUIRED_ROOTS = {"metadata", "profile", "lifecycle"}
_TYPED_REGISTRIES = {
    "phases": PhaseId,
    "artifacts": ArtifactId,
    "requirements": RequirementId,
    "decisions": DecisionId,
    "risks": RiskId,
}
_FORBIDDEN_FIELDS = {
    "contract_version",
    "content_fingerprint",
    "fingerprint",
    "project_id",
    "record_fingerprint",
}


def _scope_error(path: PatchPath, message: str, expected: str) -> ErrorDetail:
    return ErrorDetail(
        code=ErrorCode.PATCH_SCOPE_VIOLATION,
        message=message,
        path=("path",),
        entity_type="state_patch",
        expected=expected,
        actual=str(path),
        remediation_hint="Use an explicitly supported ProjectState patch path.",
        severity=Severity.ERROR,
    )


def validate_patch_path_policy(
    path: PatchPath,
    op: PatchOperationType,
) -> ErrorDetail | None:
    """Return a structured error when a path violates the K05 allowlist."""

    root = path.segments[0]
    if root not in _ROOTS:
        return _scope_error(path, "Patch path root is not supported.", "supported K05 root")
    if any(
        segment in _FORBIDDEN_FIELDS or segment.endswith("_fingerprint")
        for segment in path.segments
    ):
        return _scope_error(
            path,
            "Patch path targets protected identity, version, or fingerprint metadata.",
            "mutable domain field",
        )
    if op is PatchOperationType.REMOVE and len(path.segments) == 1 and root in _REQUIRED_ROOTS:
        return ErrorDetail(
            code=ErrorCode.IMMUTABLE_RECORD_MODIFICATION,
            message="Required ProjectState sections cannot be removed.",
            path=("path",),
            entity_type="state_patch",
            expected="non-required node",
            actual=str(path),
            remediation_hint="Replace a valid section value instead of removing the section.",
            severity=Severity.ERROR,
        )
    if (
        op is not PatchOperationType.TEST
        and root in {"decisions", "dependencies"}
        and len(path.segments) >= 3
    ):
        return ErrorDetail(
            code=ErrorCode.IMMUTABLE_RECORD_MODIFICATION,
            message="Immutable historical records cannot be modified internally.",
            path=("path",),
            entity_type="state_patch",
            expected="whole-record add, replace, remove, or observational test",
            actual=str(path),
            remediation_hint="Replace the complete immutable record or model a new record.",
            severity=Severity.ERROR,
        )
    id_type = _TYPED_REGISTRIES.get(root)
    if id_type is not None and len(path.segments) >= 2:
        try:
            id_type.from_str(path.segments[1])
        except ValueError:
            return ErrorDetail(
                code=ErrorCode.INVALID_IDENTIFIER,
                message=f"{root} path contains an ID of the wrong canonical type.",
                path=("path", 1),
                entity_type="state_patch",
                expected=f"{id_type.prefix}-<ULID>",
                actual=path.segments[1],
                remediation_hint=f"Use a canonical {id_type.__name__}.",
                severity=Severity.ERROR,
            )
    if root == "dependencies" and len(path.segments) >= 2 and not path.segments[1].isdigit():
        return _scope_error(
            path,
            "Dependency paths require a numeric index.",
            "/dependencies/<index>",
        )
    return None


__all__ = ("validate_patch_path_policy",)
