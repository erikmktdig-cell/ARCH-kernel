"""Pure atomic execution of declarative migration plans."""

from __future__ import annotations

import copy
import math
import re
from typing import Any, cast

from pydantic import ValidationError

from arch_kernel.contracts.migrations import (
    MigrationCoercion,
    MigrationDefinition,
    MigrationDisposition,
    MigrationFinding,
    MigrationOperation,
    MigrationOperationType,
    MigrationPath,
    MigrationRequest,
    MigrationResult,
    MigrationStepResult,
)
from arch_kernel.contracts.registry import ContractRegistration
from arch_kernel.kernel.contract_registry import ContractRegistry
from arch_kernel.kernel.errors import ArchKernelError, ErrorCode, Severity
from arch_kernel.kernel.event_validation import freeze_json_object, thaw_json
from arch_kernel.kernel.fingerprints import canonicalize_json, compute_fingerprint
from arch_kernel.kernel.migration_planning import resolve_migration_plan
from arch_kernel.kernel.migration_registry import MigrationRegistry
from arch_kernel.kernel.schema_generation import generate_contract_schema

_ZERO_FINGERPRINT = "sha256:" + ("0" * 64)
_INTEGER_RE = re.compile(r"^-?(?:0|[1-9]\d*)$", re.ASCII)
_NUMBER_RE = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$", re.ASCII)


class _OperationError(ValueError):
    def __init__(
        self,
        path: MigrationPath,
        message: str,
        *,
        code: ErrorCode = ErrorCode.MIGRATION_OPERATION_FAILED,
    ) -> None:
        self.path = path
        self.code = code
        super().__init__(message)


def _finding(
    code: ErrorCode,
    message: str,
    sequence: int,
    *,
    path: str | None = None,
    expected: object | None = None,
    actual: object | None = None,
) -> MigrationFinding:
    return MigrationFinding.model_validate(
        {
            "code": code.value,
            "message": message,
            "severity": Severity.ERROR,
            "blocking": True,
            "path": path,
            "expected": expected,
            "actual": actual,
            "sequence": sequence,
        }
    )


def _parent(
    document: dict[str, Any],
    path: MigrationPath,
) -> tuple[dict[str, Any], str]:
    current: Any = document
    for segment in path.segments[:-1]:
        if not isinstance(current, dict) or segment not in current:
            raise _OperationError(path, "Migration path parent does not exist.")
        current = current[segment]
    if not isinstance(current, dict):
        raise _OperationError(path, "Migration path parent is not an object.")
    return current, path.segments[-1]


def _read(document: dict[str, Any], path: MigrationPath) -> Any:
    parent, key = _parent(document, path)
    if key not in parent:
        raise _OperationError(path, "Migration path does not exist.")
    return parent[key]


def _coerce(value: Any, coercion: MigrationCoercion, path: MigrationPath) -> Any:
    if coercion is MigrationCoercion.INTEGER_TO_NUMBER:
        if isinstance(value, bool) or not isinstance(value, int):
            raise _OperationError(path, "integer_to_number requires an integer.")
        return float(value)
    if coercion is MigrationCoercion.INTEGER_TO_STRING:
        if isinstance(value, bool) or not isinstance(value, int):
            raise _OperationError(path, "integer_to_string requires an integer.")
        return str(value)
    if coercion is MigrationCoercion.NUMBER_TO_STRING:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _OperationError(path, "number_to_string requires a number.")
        if isinstance(value, float) and not math.isfinite(value):
            raise _OperationError(path, "number_to_string requires a finite number.")
        return str(value)
    if coercion is MigrationCoercion.BOOLEAN_TO_STRING:
        if not isinstance(value, bool):
            raise _OperationError(path, "boolean_to_string requires a boolean.")
        return "true" if value else "false"
    if not isinstance(value, str):
        raise _OperationError(path, f"{coercion.value} requires a string.")
    if coercion is MigrationCoercion.STRING_TO_INTEGER:
        if _INTEGER_RE.fullmatch(value) is None:
            raise _OperationError(path, "String is not a canonical integer.")
        return int(value)
    if coercion is MigrationCoercion.STRING_TO_NUMBER:
        if _NUMBER_RE.fullmatch(value) is None:
            raise _OperationError(path, "String is not a canonical number.")
        number = float(value)
        if not math.isfinite(number):
            raise _OperationError(path, "String number must be finite.")
        return number
    if coercion is MigrationCoercion.STRING_TO_BOOLEAN:
        if value not in {"true", "false"}:
            raise _OperationError(path, "String boolean must be exactly true or false.")
        return value == "true"
    raise _OperationError(path, "Unsupported migration coercion.")


def _apply_operation(
    document: dict[str, Any],
    operation: MigrationOperation,
    *,
    enum_passthrough: bool,
) -> bool:
    path = cast(MigrationPath, operation.path)
    parent, key = _parent(document, path)
    exists = key in parent
    op = operation.operation_type
    if op is MigrationOperationType.ADD:
        if exists:
            raise _OperationError(path, "add requires an absent destination.")
        parent[key] = thaw_json(operation.value)
        return True
    if op is MigrationOperationType.REPLACE:
        if not exists:
            raise _OperationError(path, "replace requires an existing destination.")
        replacement = thaw_json(operation.value)
        if canonicalize_json(parent[key]) == canonicalize_json(replacement):
            return False
        parent[key] = replacement
        return True
    if op is MigrationOperationType.REMOVE:
        if not exists:
            raise _OperationError(path, "remove requires an existing destination.")
        del parent[key]
        return True
    if op is MigrationOperationType.TEST:
        if not exists:
            raise _OperationError(
                path,
                "test requires an existing destination.",
                code=ErrorCode.MIGRATION_PRECONDITION_FAILED,
            )
        expected = thaw_json(operation.expected_value)
        if canonicalize_json(parent[key]) != canonicalize_json(expected):
            raise _OperationError(
                path,
                "test precondition failed.",
                code=ErrorCode.MIGRATION_PRECONDITION_FAILED,
            )
        return False
    if op is MigrationOperationType.SET_DEFAULT:
        if exists:
            return False
        parent[key] = thaw_json(operation.value)
        return True
    if op in {
        MigrationOperationType.MOVE,
        MigrationOperationType.COPY,
        MigrationOperationType.RENAME,
    }:
        source_path = cast(MigrationPath, operation.from_path)
        source_parent, source_key = _parent(document, source_path)
        if source_key not in source_parent:
            raise _OperationError(source_path, f"{op.value} source does not exist.")
        if exists:
            raise _OperationError(path, f"{op.value} destination must be absent.")
        parent[key] = copy.deepcopy(source_parent[source_key])
        if op in {MigrationOperationType.MOVE, MigrationOperationType.RENAME}:
            del source_parent[source_key]
        return True
    if op is MigrationOperationType.MAP_ENUM:
        if not exists:
            raise _OperationError(path, "map_enum requires an existing destination.")
        current = parent[key]
        if not isinstance(current, str):
            raise _OperationError(path, "map_enum requires a string value.")
        mapping = cast(dict[str, Any], thaw_json(operation.enum_mapping))
        if current not in mapping:
            if operation.enum_passthrough or enum_passthrough:
                return False
            raise _OperationError(path, "map_enum value is not mapped.")
        mapped = mapping[current]
        if canonicalize_json(current) == canonicalize_json(mapped):
            return False
        parent[key] = mapped
        return True
    if op is MigrationOperationType.COERCE:
        if not exists:
            raise _OperationError(path, "coerce requires an existing destination.")
        converted = _coerce(parent[key], cast(MigrationCoercion, operation.coercion), path)
        if canonicalize_json(parent[key]) == canonicalize_json(converted):
            return False
        parent[key] = converted
        return True
    raise _OperationError(path, "Unsupported migration operation.")


def _validate_payload(
    registration: ContractRegistration,
    document: dict[str, Any],
) -> dict[str, Any]:
    model = registration.model.model_validate_json(canonicalize_json(document))
    return model.model_dump(mode="json")


def _step(
    definition: MigrationDefinition,
    document: dict[str, Any],
    request: MigrationRequest,
    contract_registry: ContractRegistry,
    sequence: int,
    finding_sequence: int,
) -> tuple[MigrationStepResult, dict[str, Any] | None, int]:
    input_fingerprint = compute_fingerprint(document)
    candidate = copy.deepcopy(document)
    changed: list[MigrationPath] = []
    try:
        for operation in definition.operations:
            if _apply_operation(
                candidate,
                operation,
                enum_passthrough=request.policy.enum_passthrough,
            ):
                path = cast(MigrationPath, operation.path)
                if path not in changed:
                    changed.append(path)
        if request.policy.validate_each_step:
            registration = contract_registry.get(
                definition.canonical_name, definition.target_version
            )
            if registration is None:
                raise ValueError("Migration step target registration disappeared.")
            candidate = _validate_payload(registration, candidate)
    except (_OperationError, ValidationError, ValueError) as error:
        if isinstance(error, _OperationError):
            code = error.code
            error_path = str(error.path)
        elif isinstance(error, ValidationError):
            code = ErrorCode.MIGRATION_TARGET_VALIDATION_FAILED
            error_path = None
        else:
            code = ErrorCode.INVALID_MIGRATION_DEFINITION
            error_path = None
        finding = _finding(
            code,
            str(error),
            finding_sequence,
            path=error_path,
        )
        return (
            MigrationStepResult(
                migration_id=definition.migration_id,
                key=definition.key,
                source_version=definition.source_version,
                target_version=definition.target_version,
                success=False,
                blocking_failure=True,
                findings=(finding,),
                input_fingerprint=input_fingerprint,
                output_fingerprint=None,
                changed_paths=(),
                output_payload=None,
                sequence=sequence,
            ),
            None,
            finding_sequence + 1,
        )
    output_fingerprint = compute_fingerprint(candidate)
    return (
        MigrationStepResult(
            migration_id=definition.migration_id,
            key=definition.key,
            source_version=definition.source_version,
            target_version=definition.target_version,
            success=True,
            blocking_failure=False,
            findings=(),
            input_fingerprint=input_fingerprint,
            output_fingerprint=output_fingerprint,
            changed_paths=tuple(changed),
            output_payload=(
                freeze_json_object(candidate)
                if request.policy.expose_intermediate_payloads
                else None
            ),
            sequence=sequence,
        ),
        candidate,
        finding_sequence,
    )


def run_migration_dry_run(
    request: MigrationRequest,
    migration_registry: MigrationRegistry,
    contract_registry: ContractRegistry,
) -> MigrationResult:
    """Resolve, execute, and validate one migration without mutating inputs."""

    source_document = cast(dict[str, Any], thaw_json(request.source_payload))
    source_fingerprint = compute_fingerprint(source_document)
    request_fingerprint = compute_fingerprint(request, exclude_fields={"evaluated_at"})
    findings: list[MigrationFinding] = []
    source_registration = contract_registry.get(request.canonical_name, request.source_version)
    target_registration = contract_registry.get(request.canonical_name, request.target_version)
    source_schema = (
        generate_contract_schema(source_registration).schema_fingerprint
        if source_registration is not None
        else None
    )
    target_schema = (
        generate_contract_schema(target_registration).schema_fingerprint
        if target_registration is not None
        else None
    )
    if (
        request.expected_source_payload_fingerprint is not None
        and request.expected_source_payload_fingerprint != source_fingerprint
    ):
        findings.append(
            _finding(
                ErrorCode.MIGRATION_PRECONDITION_FAILED,
                "Expected source payload fingerprint is stale.",
                1,
                expected=request.expected_source_payload_fingerprint,
                actual=source_fingerprint,
            )
        )
    if source_registration is None or target_registration is None:
        findings.append(
            _finding(
                ErrorCode.MIGRATION_ENDPOINT_NOT_FOUND,
                "Migration endpoint is absent from ContractRegistry.",
                len(findings) + 1,
            )
        )
    if not findings and request.policy.validate_source and source_registration is not None:
        try:
            source_document = _validate_payload(source_registration, source_document)
            source_fingerprint = compute_fingerprint(source_document)
        except ValidationError as error:
            findings.append(
                _finding(
                    ErrorCode.MIGRATION_SOURCE_VALIDATION_FAILED,
                    "Source payload failed exact model validation.",
                    1,
                    actual=error.errors()[0]["type"],
                )
            )
    plan = None
    if not findings:
        try:
            plan = resolve_migration_plan(request, migration_registry, contract_registry)
        except ArchKernelError as error:
            findings.append(
                _finding(
                    error.detail.code,
                    error.detail.message,
                    1,
                    expected=error.detail.expected,
                    actual=error.detail.actual,
                )
            )
    steps: list[MigrationStepResult] = []
    document = copy.deepcopy(source_document)
    finding_sequence = len(findings) + 1
    if plan is not None:
        for sequence, migration_id in enumerate(plan.migration_ids, start=1):
            definition = migration_registry.get_by_id(migration_id)
            if definition is None:
                findings.append(
                    _finding(
                        ErrorCode.INVALID_MIGRATION_DEFINITION,
                        "Resolved migration definition disappeared.",
                        finding_sequence,
                    )
                )
                break
            result, projected, finding_sequence = _step(
                definition,
                document,
                request,
                contract_registry,
                sequence,
                finding_sequence,
            )
            steps.append(result)
            findings.extend(result.findings)
            if projected is None:
                break
            document = projected
    target_validated = False
    if (
        plan is not None
        and not findings
        and request.policy.validate_target
        and target_registration is not None
    ):
        try:
            document = _validate_payload(target_registration, document)
            target_validated = True
        except ValidationError as error:
            findings.append(
                _finding(
                    ErrorCode.MIGRATION_TARGET_VALIDATION_FAILED,
                    "Final payload failed exact target model validation.",
                    finding_sequence,
                    actual=error.errors()[0]["type"],
                )
            )
    elif plan is not None and not findings:
        target_validated = not request.policy.validate_target
    success = plan is not None and not findings and target_validated
    not_required = success and plan is not None and plan.total_steps == 0
    disposition = (
        MigrationDisposition.NOT_REQUIRED
        if not_required
        else MigrationDisposition.SUCCEEDED
        if success
        else MigrationDisposition.FAILED
    )
    final_payload = freeze_json_object(document) if success else None
    final_fingerprint = compute_fingerprint(document) if success else None
    values = {
        "disposition": disposition,
        "success": success,
        "blocking_failure": bool(findings),
        "request_fingerprint": request_fingerprint,
        "plan": plan,
        "step_results": tuple(steps),
        "findings": tuple(findings),
        "final_payload": final_payload,
        "source_payload_fingerprint": source_fingerprint,
        "final_payload_fingerprint": final_fingerprint,
        "source_schema_fingerprint": source_schema,
        "target_schema_fingerprint": target_schema,
        "target_validated": target_validated,
        "evaluated_at": request.evaluated_at,
        "result_fingerprint": _ZERO_FINGERPRINT,
    }
    provisional = MigrationResult.model_validate(values)
    semantic = provisional.model_dump(mode="json", exclude={"evaluated_at", "result_fingerprint"})
    return provisional.model_copy(update={"result_fingerprint": compute_fingerprint(semantic)})


__all__ = ("run_migration_dry_run",)
