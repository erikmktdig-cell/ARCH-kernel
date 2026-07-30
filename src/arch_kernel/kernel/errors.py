"""Structured errors for deterministic kernel validation."""

from __future__ import annotations

from enum import StrEnum, unique

from pydantic import BaseModel, ConfigDict

type JsonScalar = str | int | float | bool
type PathSegment = str | int


@unique
class ErrorCode(StrEnum):
    """Canonical error codes emitted by the contract kernel."""

    SCHEMA_VALIDATION_ERROR = "SCHEMA_VALIDATION_ERROR"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    INVALID_ENUM_VALUE = "INVALID_ENUM_VALUE"
    INVALID_IDENTIFIER = "INVALID_IDENTIFIER"
    INVALID_REFERENCE = "INVALID_REFERENCE"
    REFERENCE_TYPE_MISMATCH = "REFERENCE_TYPE_MISMATCH"
    UNSUPPORTED_CONTRACT_VERSION = "UNSUPPORTED_CONTRACT_VERSION"
    INVALID_EVENT_TYPE = "INVALID_EVENT_TYPE"
    INVALID_EVENT_TIMESTAMP_ORDER = "INVALID_EVENT_TIMESTAMP_ORDER"
    INVALID_CAUSAL_REFERENCE = "INVALID_CAUSAL_REFERENCE"
    INVALID_IDEMPOTENCY_KEY = "INVALID_IDEMPOTENCY_KEY"
    INVALID_EVENT_PAYLOAD = "INVALID_EVENT_PAYLOAD"
    STALE_STATE_VERSION = "STALE_STATE_VERSION"
    STALE_OBJECT_VERSION = "STALE_OBJECT_VERSION"
    PATCH_SCOPE_VIOLATION = "PATCH_SCOPE_VIOLATION"
    IMMUTABLE_RECORD_MODIFICATION = "IMMUTABLE_RECORD_MODIFICATION"
    PATCH_TEST_FAILED = "PATCH_TEST_FAILED"
    TRANSITION_NOT_FOUND = "TRANSITION_NOT_FOUND"
    AMBIGUOUS_TRANSITION = "AMBIGUOUS_TRANSITION"
    TRANSITION_GUARD_FAILED = "TRANSITION_GUARD_FAILED"
    INVALID_TRANSITION_DEFINITION = "INVALID_TRANSITION_DEFINITION"
    UNSUPPORTED_TRANSITION_DOMAIN = "UNSUPPORTED_TRANSITION_DOMAIN"
    DUPLICATE_INVARIANT_ID = "DUPLICATE_INVARIANT_ID"
    DUPLICATE_INVARIANT_KEY = "DUPLICATE_INVARIANT_KEY"
    INVALID_INVARIANT_DEFINITION = "INVALID_INVARIANT_DEFINITION"
    INVARIANT_EVALUATION_ERROR = "INVARIANT_EVALUATION_ERROR"
    INVARIANT_VIOLATION = "INVARIANT_VIOLATION"
    INVALID_VALIDATION_REQUEST = "INVALID_VALIDATION_REQUEST"
    MISSING_TRANSITION_REGISTRY = "MISSING_TRANSITION_REGISTRY"
    MISSING_INVARIANT_REGISTRY = "MISSING_INVARIANT_REGISTRY"
    VALIDATION_STAGE_FAILED = "VALIDATION_STAGE_FAILED"
    VALIDATION_PIPELINE_INCONSISTENCY = "VALIDATION_PIPELINE_INCONSISTENCY"
    DUPLICATE_CONTRACT_IDENTITY = "DUPLICATE_CONTRACT_IDENTITY"
    DUPLICATE_CONTRACT_ALIAS = "DUPLICATE_CONTRACT_ALIAS"
    CONTRACT_ALIAS_COLLISION = "CONTRACT_ALIAS_COLLISION"
    CONTRACT_MODEL_MISMATCH = "CONTRACT_MODEL_MISMATCH"
    INVALID_CONTRACT_DESCRIPTOR = "INVALID_CONTRACT_DESCRIPTOR"
    SCHEMA_GENERATION_FAILED = "SCHEMA_GENERATION_FAILED"
    SCHEMA_PUBLICATION_FAILED = "SCHEMA_PUBLICATION_FAILED"
    SCHEMA_COMPATIBILITY_UNKNOWN = "SCHEMA_COMPATIBILITY_UNKNOWN"
    INADEQUATE_VERSION_BUMP = "INADEQUATE_VERSION_BUMP"
    DUPLICATE_MIGRATION_ID = "DUPLICATE_MIGRATION_ID"
    DUPLICATE_MIGRATION_KEY = "DUPLICATE_MIGRATION_KEY"
    DUPLICATE_MIGRATION_EDGE = "DUPLICATE_MIGRATION_EDGE"
    INVALID_MIGRATION_DEFINITION = "INVALID_MIGRATION_DEFINITION"
    MIGRATION_ENDPOINT_NOT_FOUND = "MIGRATION_ENDPOINT_NOT_FOUND"
    MIGRATION_PATH_NOT_FOUND = "MIGRATION_PATH_NOT_FOUND"
    AMBIGUOUS_MIGRATION_PATH = "AMBIGUOUS_MIGRATION_PATH"
    MIGRATION_POLICY_VIOLATION = "MIGRATION_POLICY_VIOLATION"
    MIGRATION_PRECONDITION_FAILED = "MIGRATION_PRECONDITION_FAILED"
    MIGRATION_OPERATION_FAILED = "MIGRATION_OPERATION_FAILED"
    MIGRATION_SOURCE_VALIDATION_FAILED = "MIGRATION_SOURCE_VALIDATION_FAILED"
    MIGRATION_TARGET_VALIDATION_FAILED = "MIGRATION_TARGET_VALIDATION_FAILED"
    MIGRATION_SCHEMA_FINGERPRINT_MISMATCH = "MIGRATION_SCHEMA_FINGERPRINT_MISMATCH"
    MIGRATION_REVERSIBILITY_INVALID = "MIGRATION_REVERSIBILITY_INVALID"
    MIGRATION_AUDIT_FAILED = "MIGRATION_AUDIT_FAILED"


@unique
class Severity(StrEnum):
    """Severity levels for structured errors."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ErrorDetail(BaseModel):
    """Deterministic error payload suitable for future validation reports."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: ErrorCode
    message: str
    path: tuple[PathSegment, ...] = ()
    entity_type: str | None = None
    entity_id: str | None = None
    expected: JsonScalar | None = None
    actual: JsonScalar | None = None
    remediation_hint: str | None = None
    severity: Severity = Severity.ERROR


def _make_error_detail(
    code: ErrorCode,
    message: str,
    *,
    path: tuple[PathSegment, ...] = (),
    entity_type: str | None = None,
    entity_id: str | None = None,
    expected: JsonScalar | None = None,
    actual: JsonScalar | None = None,
    remediation_hint: str | None = None,
    severity: Severity = Severity.ERROR,
) -> ErrorDetail:
    return ErrorDetail(
        code=code,
        message=message,
        path=path,
        entity_type=entity_type,
        entity_id=entity_id,
        expected=expected,
        actual=actual,
        remediation_hint=remediation_hint,
        severity=severity,
    )


class ArchKernelError(ValueError):
    """Base exception that carries structured kernel error details."""

    def __init__(self, detail: ErrorDetail) -> None:
        self.detail = detail
        super().__init__(detail.message)

    def to_detail(self) -> ErrorDetail:
        """Return the structured error detail associated with this exception."""

        return self.detail


class IdentifierValidationError(ArchKernelError):
    """Raised when a canonical identifier is malformed or type-mismatched."""

    def __init__(
        self,
        message: str,
        *,
        path: tuple[PathSegment, ...] = (),
        entity_type: str | None = None,
        entity_id: str | None = None,
        expected: JsonScalar | None = None,
        actual: JsonScalar | None = None,
        remediation_hint: str | None = None,
        severity: Severity = Severity.ERROR,
    ) -> None:
        super().__init__(
            _make_error_detail(
                ErrorCode.INVALID_IDENTIFIER,
                message,
                path=path,
                entity_type=entity_type,
                entity_id=entity_id,
                expected=expected,
                actual=actual,
                remediation_hint=remediation_hint,
                severity=severity,
            )
        )


class VersionValidationError(ArchKernelError):
    """Raised when a semantic version cannot be parsed or compared."""

    def __init__(
        self,
        message: str,
        *,
        path: tuple[PathSegment, ...] = (),
        entity_type: str | None = "semantic_version",
        entity_id: str | None = None,
        expected: JsonScalar | None = "SemVer 2.0.0",
        actual: JsonScalar | None = None,
        remediation_hint: str | None = None,
        severity: Severity = Severity.ERROR,
    ) -> None:
        super().__init__(
            _make_error_detail(
                ErrorCode.SCHEMA_VALIDATION_ERROR,
                message,
                path=path,
                entity_type=entity_type,
                entity_id=entity_id,
                expected=expected,
                actual=actual,
                remediation_hint=remediation_hint,
                severity=severity,
            )
        )


class ReferenceValidationError(ArchKernelError):
    """Raised when a typed or evidence reference is invalid."""

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode = ErrorCode.INVALID_REFERENCE,
        path: tuple[PathSegment, ...] = (),
        entity_type: str | None = "reference",
        entity_id: str | None = None,
        expected: JsonScalar | None = None,
        actual: JsonScalar | None = None,
        remediation_hint: str | None = None,
        severity: Severity = Severity.ERROR,
    ) -> None:
        super().__init__(
            _make_error_detail(
                code,
                message,
                path=path,
                entity_type=entity_type,
                entity_id=entity_id,
                expected=expected,
                actual=actual,
                remediation_hint=remediation_hint,
                severity=severity,
            )
        )


class EventValidationError(ArchKernelError):
    """Raised when an event envelope violates a local event contract rule."""

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode,
        path: tuple[PathSegment, ...] = (),
        entity_type: str | None = "event",
        entity_id: str | None = None,
        expected: JsonScalar | None = None,
        actual: JsonScalar | None = None,
        remediation_hint: str | None = None,
        severity: Severity = Severity.ERROR,
    ) -> None:
        super().__init__(
            _make_error_detail(
                code,
                message,
                path=path,
                entity_type=entity_type,
                entity_id=entity_id,
                expected=expected,
                actual=actual,
                remediation_hint=remediation_hint,
                severity=severity,
            )
        )


__all__ = (
    "ArchKernelError",
    "ErrorCode",
    "ErrorDetail",
    "EventValidationError",
    "IdentifierValidationError",
    "ReferenceValidationError",
    "Severity",
    "VersionValidationError",
)
