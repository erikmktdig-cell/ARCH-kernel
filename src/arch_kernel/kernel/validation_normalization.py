"""Pure diagnostic normalization for the WP-K08 pipeline."""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from pydantic import ValidationError

from arch_kernel.contracts.invariants import InvariantEvaluationResult
from arch_kernel.contracts.validation import (
    InvariantEvaluationTarget,
    ValidationFinding,
    ValidationFindingKind,
    ValidationJsonValue,
    ValidationStage,
)
from arch_kernel.kernel.errors import ArchKernelError, ErrorCode, ErrorDetail, Severity


def _path(segments: Iterable[str | int]) -> str:
    items = tuple(str(segment) for segment in segments)
    return "/" + "/".join(items) if items else "/"


def normalize_error_details(
    errors: Iterable[ErrorDetail],
    *,
    stage: ValidationStage,
    kind: ValidationFindingKind,
    start_sequence: int = 1,
) -> tuple[ValidationFinding, ...]:
    """Convert kernel ErrorDetail values without losing their structured fields."""

    return tuple(
        ValidationFinding(
            kind=(
                ValidationFindingKind.GUARD_FAILURE
                if error.code is ErrorCode.TRANSITION_GUARD_FAILED
                else kind
            ),
            stage=stage,
            code=error.code.value,
            message=error.message,
            severity=error.severity,
            blocking=error.severity in {Severity.ERROR, Severity.CRITICAL},
            sequence=start_sequence + index,
            path=_path(error.path) if error.path else None,
            entity_type=error.entity_type,
            entity_id=error.entity_id,
            expected=error.expected,
            actual=error.actual,
            remediation_hint=error.remediation_hint,
        )
        for index, error in enumerate(errors)
    )


def normalize_pydantic_error(
    error: ValidationError,
    *,
    stage: ValidationStage,
    kind: ValidationFindingKind,
    start_sequence: int = 1,
) -> tuple[ValidationFinding, ...]:
    """Convert Pydantic details in stable declared order."""

    findings: list[ValidationFinding] = []
    for index, detail in enumerate(error.errors(include_url=False)):
        context = detail.get("ctx") or {}
        nested = context.get("error")
        if isinstance(nested, ArchKernelError):
            findings.extend(
                normalize_error_details(
                    (nested.detail,),
                    stage=stage,
                    kind=kind,
                    start_sequence=start_sequence + index,
                )
            )
            continue
        findings.append(
            ValidationFinding(
                kind=kind,
                stage=stage,
                code=str(detail["type"]).upper(),
                message=str(detail["msg"]),
                severity=Severity.ERROR,
                blocking=True,
                sequence=start_sequence + index,
                path=_path(detail["loc"]),
                expected=None,
                actual=str(detail.get("input"))[:240],
            )
        )
    return tuple(findings)


def normalize_invariant_result(
    result: InvariantEvaluationResult,
    *,
    target: InvariantEvaluationTarget,
    start_sequence: int = 1,
) -> tuple[ValidationFinding, ...]:
    """Map each invariant violation to exactly one stable pipeline finding."""

    findings: list[ValidationFinding] = []
    for violation in result.violations:
        evidence = [
            {
                "reference": (
                    item.reference.model_dump(mode="json") if item.reference is not None else None
                ),
                "path": item.path,
                "observed": item.observed,
                "expected": item.expected,
                "message": item.message,
            }
            for item in violation.evidence
        ]
        first = violation.evidence[0]
        findings.append(
            ValidationFinding(
                kind=ValidationFindingKind.INVARIANT_VIOLATION,
                stage=ValidationStage.INVARIANT,
                code=ErrorCode.INVARIANT_VIOLATION.value,
                message=violation.message,
                severity=Severity(violation.severity.value),
                blocking=violation.blocking,
                sequence=start_sequence + len(findings),
                path=first.path,
                entity_type=(
                    first.reference.target_type
                    if first.reference is not None
                    else violation.scope.value
                ),
                entity_id=(str(first.reference.target_id) if first.reference is not None else None),
                actual=cast(ValidationJsonValue, evidence),
                remediation_hint=violation.remediation_hint,
                source_id=str(violation.invariant_id),
                source_key=violation.key,
                source_target=target,
            )
        )
    findings.extend(
        normalize_error_details(
            result.errors,
            stage=ValidationStage.INVARIANT,
            kind=ValidationFindingKind.PIPELINE_ERROR,
            start_sequence=start_sequence + len(findings),
        )
    )
    return tuple(findings)


__all__ = (
    "normalize_error_details",
    "normalize_invariant_result",
    "normalize_pydantic_error",
)
