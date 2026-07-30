import pytest
from pydantic import ValidationError

from arch_kernel.kernel import (
    ArchKernelError,
    ErrorCode,
    ErrorDetail,
    IdentifierValidationError,
    Severity,
)


def test_error_detail_is_structured_and_serializable() -> None:
    detail = ErrorDetail(
        code=ErrorCode.INVALID_IDENTIFIER,
        message="Invalid ID.",
        path=("artifact_id",),
        entity_type="artifact",
        entity_id="ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1A",
        expected="ART-<ULID>",
        actual="REQ-01HZX7M3FQ1T2Q9V8Y6K4C2B1A",
        remediation_hint="Use an ArtifactId.",
        severity=Severity.ERROR,
    )

    assert detail.model_dump(mode="json") == {
        "code": "INVALID_IDENTIFIER",
        "message": "Invalid ID.",
        "path": ["artifact_id"],
        "entity_type": "artifact",
        "entity_id": "ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1A",
        "expected": "ART-<ULID>",
        "actual": "REQ-01HZX7M3FQ1T2Q9V8Y6K4C2B1A",
        "remediation_hint": "Use an ArtifactId.",
        "severity": "error",
    }


def test_error_detail_is_immutable() -> None:
    detail = ErrorDetail(code=ErrorCode.UNKNOWN_FIELD, message="Unknown field.")

    with pytest.raises(ValidationError):
        detail.message = "Changed."


def test_exception_exposes_structured_detail() -> None:
    error = IdentifierValidationError(
        "Invalid identifier.",
        path=("target_id",),
        expected="ART-<ULID>",
        actual="REQ-...",
    )

    assert isinstance(error, ArchKernelError)
    assert str(error) == "Invalid identifier."
    assert error.to_detail().code == ErrorCode.INVALID_IDENTIFIER
    assert error.to_detail().path == ("target_id",)
