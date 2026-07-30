"""Unified pure orchestration across the K03-K07 validation engines."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from arch_kernel.contracts.invariants import InvariantEvaluationContext
from arch_kernel.contracts.patches import StatePatch
from arch_kernel.contracts.project_state import ProjectState
from arch_kernel.contracts.validation import (
    InvariantEvaluationTarget,
    ValidationDisposition,
    ValidationFinding,
    ValidationFindingKind,
    ValidationIntent,
    ValidationPipelineRequest,
    ValidationPipelineResult,
    ValidationStage,
    ValidationStageResult,
)
from arch_kernel.kernel.errors import ArchKernelError, ErrorCode, Severity
from arch_kernel.kernel.event_validation import freeze_json_object, freeze_json_value
from arch_kernel.kernel.fingerprints import canonicalize_json, compute_fingerprint
from arch_kernel.kernel.invariant_evaluation import evaluate_invariants
from arch_kernel.kernel.invariant_registry import InvariantRegistry
from arch_kernel.kernel.patch_application import (
    apply_state_patch_dry_run,
    validate_state_patch,
)
from arch_kernel.kernel.transition_evaluation import evaluate_transition
from arch_kernel.kernel.transition_registry import TransitionRegistry
from arch_kernel.kernel.validation_normalization import (
    normalize_error_details,
    normalize_invariant_result,
    normalize_pydantic_error,
)

_ZERO_FINGERPRINT = "sha256:" + ("0" * 64)
_STAGE_KIND = {
    ValidationStage.CONTRACT: ValidationFindingKind.CONTRACT_ERROR,
    ValidationStage.AGGREGATE: ValidationFindingKind.AGGREGATE_ERROR,
    ValidationStage.PATCH: ValidationFindingKind.PATCH_ERROR,
    ValidationStage.TRANSITION: ValidationFindingKind.TRANSITION_ERROR,
    ValidationStage.INVARIANT: ValidationFindingKind.INVARIANT_VIOLATION,
    ValidationStage.FINALIZATION: ValidationFindingKind.PIPELINE_ERROR,
}


def _json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json(item) for item in value]
    return value


def _strip_volatile(value: Any, *, root: bool = True) -> Any:
    if isinstance(value, Mapping):
        is_stage = "stage" in value and "executed" in value
        return {
            str(key): _strip_volatile(item, root=False)
            for key, item in value.items()
            if not str(key).endswith("_at")
            and not (is_stage and key in {"input_fingerprint", "output_fingerprint"})
        }
    if isinstance(value, (list, tuple)):
        return [_strip_volatile(item, root=False) for item in value]
    return value


def _registry_payload(registry: object | None) -> object | None:
    if registry is None:
        return None
    if isinstance(registry, TransitionRegistry):
        return tuple(_json(item) for item in registry.definitions)
    if isinstance(registry, InvariantRegistry):
        return tuple(_json(item) for item in registry.definitions)
    raise TypeError("Unsupported registry type.")


def _input_fingerprint(
    request: ValidationPipelineRequest,
    transition_registry: TransitionRegistry | None,
    invariant_registry: InvariantRegistry | None,
) -> str:
    typed_state = _json(request.state) if request.state is not None else None
    raw_state = _json(request.raw_state) if request.raw_state is not None else None
    state_payload: object = typed_state if typed_state is not None else raw_state
    if typed_state is not None and raw_state is not None and typed_state != raw_state:
        state_payload = {"typed": typed_state, "raw": raw_state}
    typed_patch = _json(request.patch) if request.patch is not None else None
    raw_patch = _json(request.raw_patch) if request.raw_patch is not None else None
    patch_payload: object = typed_patch if typed_patch is not None else raw_patch
    if typed_patch is not None and raw_patch is not None and typed_patch != raw_patch:
        patch_payload = {"typed": typed_patch, "raw": raw_patch}
    payload = {
        "intent": request.intent.value,
        "state": state_payload,
        "patch": patch_payload,
        "transition_request": _json(request.transition_request),
        "event_history": _json(request.event_history),
        "previous_snapshots": _json(request.previous_snapshots),
        "selected_invariant_keys": request.selected_invariant_keys,
        "selected_invariant_scopes": _json(request.selected_invariant_scopes),
        "policy": _json(request.policy),
    }
    payload["transition_registry"] = _registry_payload(transition_registry)
    payload["invariant_registry"] = _registry_payload(invariant_registry)
    return compute_fingerprint(payload)


def _pipeline_finding(
    stage: ValidationStage,
    code: ErrorCode,
    message: str,
    *,
    actual: object | None = None,
    expected: object | None = None,
    blocking: bool = True,
) -> ValidationFinding:
    return ValidationFinding(
        kind=ValidationFindingKind.PIPELINE_ERROR,
        stage=stage,
        code=code.value,
        message=message,
        severity=Severity.ERROR if blocking else Severity.WARNING,
        blocking=blocking,
        sequence=1,
        expected=freeze_json_value(expected) if expected is not None else None,
        actual=freeze_json_value(actual) if actual is not None else None,
    )


def _stage(
    stage: ValidationStage,
    *,
    executed: bool = False,
    findings: tuple[ValidationFinding, ...] = (),
    metadata: Mapping[str, object] | None = None,
    input_fingerprint: str | None = None,
    output_fingerprint: str | None = None,
) -> ValidationStageResult:
    return ValidationStageResult(
        stage=stage,
        executed=executed,
        success=not any(finding.blocking for finding in findings),
        blocking_failure=any(finding.blocking for finding in findings),
        findings=findings,
        metadata=freeze_json_object(dict(metadata or {})),
        input_fingerprint=input_fingerprint,
        output_fingerprint=output_fingerprint,
    )


def _enabled(request: ValidationPipelineRequest, stage: ValidationStage) -> bool:
    enabled = request.policy.enabled_stages
    return enabled is None or stage in enabled


def _parse_pair[ParsedModel: (ProjectState, StatePatch)](
    typed: ParsedModel | None,
    raw: Mapping[str, object] | None,
    model: type[ParsedModel],
) -> ParsedModel:
    parsed = model.model_validate_json(canonicalize_json(raw)) if raw is not None else None
    if typed is not None and parsed is not None:
        if typed.model_dump(mode="json") != parsed.model_dump(mode="json"):
            raise ValueError("Typed and raw representations describe different values.")
        return typed
    if typed is not None:
        return typed
    if parsed is not None:
        return parsed
    raise ValueError("A typed or raw representation is required.")


def _default_target(intent: ValidationIntent) -> InvariantEvaluationTarget:
    if intent in {
        ValidationIntent.VALIDATE_PATCH,
        ValidationIntent.VALIDATE_TRANSITION,
    }:
        return InvariantEvaluationTarget.PROJECTED
    return InvariantEvaluationTarget.ORIGINAL


def _invariants_required(request: ValidationPipelineRequest) -> bool:
    if not _enabled(request, ValidationStage.INVARIANT):
        return False
    if request.intent is ValidationIntent.VALIDATE_STATE:
        return (
            request.policy.invariant_target is not None
            or request.selected_invariant_keys is not None
            or request.selected_invariant_scopes is not None
            or request.policy.selected_invariant_keys is not None
            or request.policy.selected_invariant_scopes is not None
        )
    return True


def _selection(
    request_value: tuple[Any, ...] | None,
    policy_value: tuple[Any, ...] | None,
    field_name: str,
) -> tuple[Any, ...] | None:
    if request_value is not None and policy_value is not None and request_value != policy_value:
        raise ValueError(f"Conflicting request and policy values for {field_name}.")
    return request_value if request_value is not None else policy_value


def _resequence(
    stages: tuple[ValidationStageResult, ...],
) -> tuple[ValidationStageResult, ...]:
    sequence = 1
    result: list[ValidationStageResult] = []
    for stage in stages:
        findings = tuple(
            finding.model_copy(update={"sequence": sequence + index})
            for index, finding in enumerate(stage.findings)
        )
        sequence += len(findings)
        result.append(stage.model_copy(update={"findings": findings}))
    return tuple(result)


def _counts(findings: tuple[ValidationFinding, ...], field: str, values: tuple[Any, ...]) -> object:
    return freeze_json_object(
        {
            item.value: sum(getattr(finding, field) is item for finding in findings)
            for item in values
        }
    )


def _disposition(
    findings: tuple[ValidationFinding, ...],
    stages: tuple[ValidationStageResult, ...],
    *,
    invalid_input: bool,
    non_blocking_affects: bool,
) -> ValidationDisposition:
    if invalid_input:
        return ValidationDisposition.INVALID_INPUT
    if any(finding.blocking for finding in findings):
        return ValidationDisposition.REJECTED
    if findings and non_blocking_affects:
        return ValidationDisposition.ACCEPTED_WITH_FINDINGS
    if not any(stage.executed for stage in stages[1:-1]):
        return ValidationDisposition.NOT_EVALUATED
    return ValidationDisposition.ACCEPTED


def run_validation_pipeline(
    request: ValidationPipelineRequest,
    *,
    transition_registry: TransitionRegistry | None = None,
    invariant_registry: InvariantRegistry | None = None,
) -> ValidationPipelineResult:
    """Run six canonical stages while delegating every domain decision."""

    input_fingerprint = _input_fingerprint(request, transition_registry, invariant_registry)
    stages = {stage: _stage(stage) for stage in ValidationStage}
    state: ProjectState | None = None
    patch: StatePatch | None = None
    projected_state: ProjectState | None = None
    generated_patch: StatePatch | None = None
    transition_summary: object | None = None
    invariant_summary: object | None = None
    invalid_input = False
    stop = False

    contract_findings: tuple[ValidationFinding, ...] = ()
    try:
        state = _parse_pair(request.state, request.raw_state, ProjectState)
        if request.intent is ValidationIntent.VALIDATE_PATCH:
            patch = _parse_pair(request.patch, request.raw_patch, StatePatch)
        _selection(
            request.selected_invariant_keys,
            request.policy.selected_invariant_keys,
            "selected_invariant_keys",
        )
        _selection(
            request.selected_invariant_scopes,
            request.policy.selected_invariant_scopes,
            "selected_invariant_scopes",
        )
        if (
            request.expected_input_fingerprint is not None
            and request.expected_input_fingerprint != input_fingerprint
        ):
            contract_findings = (
                _pipeline_finding(
                    ValidationStage.CONTRACT,
                    ErrorCode.INVALID_VALIDATION_REQUEST,
                    "Expected input fingerprint does not match semantic pipeline input.",
                    expected=request.expected_input_fingerprint,
                    actual=input_fingerprint,
                ),
            )
    except ValidationError as error:
        contract_findings = normalize_pydantic_error(
            error,
            stage=ValidationStage.CONTRACT,
            kind=ValidationFindingKind.CONTRACT_ERROR,
        )
    except (TypeError, ValueError) as error:
        contract_findings = (
            _pipeline_finding(
                ValidationStage.CONTRACT,
                ErrorCode.INVALID_VALIDATION_REQUEST,
                str(error),
            ),
        )
    stages[ValidationStage.CONTRACT] = _stage(
        ValidationStage.CONTRACT,
        executed=True,
        findings=contract_findings,
        metadata={"intent": request.intent.value},
        input_fingerprint=input_fingerprint,
    )
    if contract_findings:
        invalid_input = True
        stop = True

    if not stop and state is not None:
        try:
            state = ProjectState.model_validate_json(canonicalize_json(state))
            stages[ValidationStage.AGGREGATE] = _stage(
                ValidationStage.AGGREGATE,
                executed=True,
                metadata={"record_version": state.record_version},
                input_fingerprint=state.record_fingerprint(),
                output_fingerprint=state.contract_content_fingerprint(),
            )
        except ValidationError as error:
            findings = normalize_pydantic_error(
                error,
                stage=ValidationStage.AGGREGATE,
                kind=ValidationFindingKind.AGGREGATE_ERROR,
            )
            stages[ValidationStage.AGGREGATE] = _stage(
                ValidationStage.AGGREGATE,
                executed=True,
                findings=findings,
            )
            stop = True

    if (
        not stop
        and request.intent is ValidationIntent.VALIDATE_PATCH
        and _enabled(request, ValidationStage.PATCH)
        and state is not None
        and patch is not None
    ):
        validation = validate_state_patch(state, patch)
        dry_run = apply_state_patch_dry_run(state, patch, evaluated_at=request.evaluated_at)
        findings = normalize_error_details(
            dry_run.validation.errors or validation.errors,
            stage=ValidationStage.PATCH,
            kind=ValidationFindingKind.PATCH_ERROR,
        ) + normalize_error_details(
            dry_run.validation.warnings or validation.warnings,
            stage=ValidationStage.PATCH,
            kind=ValidationFindingKind.PATCH_ERROR,
            start_sequence=1 + len(dry_run.validation.errors or validation.errors),
        )
        projected_state = dry_run.projected_state
        stages[ValidationStage.PATCH] = _stage(
            ValidationStage.PATCH,
            executed=True,
            findings=findings,
            metadata={
                "status": dry_run.status.value,
                "changed_paths": [str(path) for path in dry_run.changed_paths],
            },
            input_fingerprint=dry_run.original_state_content_fingerprint,
            output_fingerprint=dry_run.projected_state_content_fingerprint,
        )
        if any(finding.blocking for finding in findings):
            stop = not request.policy.continue_after_blocking_failure

    if (
        not stop
        and request.intent is ValidationIntent.VALIDATE_TRANSITION
        and _enabled(request, ValidationStage.TRANSITION)
        and state is not None
    ):
        if transition_registry is None:
            findings = (
                _pipeline_finding(
                    ValidationStage.TRANSITION,
                    ErrorCode.MISSING_TRANSITION_REGISTRY,
                    "validate_transition requires a TransitionRegistry.",
                ),
            )
            stages[ValidationStage.TRANSITION] = _stage(
                ValidationStage.TRANSITION, executed=True, findings=findings
            )
            invalid_input = True
            stop = True
        else:
            transition = evaluate_transition(
                state,
                request.transition_request,  # type: ignore[arg-type]
                transition_registry,
                evaluated_at=request.evaluated_at,
            )
            findings = normalize_error_details(
                transition.errors,
                stage=ValidationStage.TRANSITION,
                kind=ValidationFindingKind.TRANSITION_ERROR,
            )
            generated_patch = transition.state_patch
            if transition.dry_run_result is not None:
                projected_state = transition.dry_run_result.projected_state
            transition_summary = {
                "allowed": transition.allowed,
                "transition_id": (
                    str(transition.transition.transition_id)
                    if transition.transition is not None
                    else None
                ),
                "transition_key": (
                    transition.transition.transition_key
                    if transition.transition is not None
                    else None
                ),
                "current_state": transition.current_state,
                "target_state": transition.target_state,
                "guards_evaluated": len(transition.guard_evaluations),
            }
            stages[ValidationStage.TRANSITION] = _stage(
                ValidationStage.TRANSITION,
                executed=True,
                findings=findings,
                metadata=transition_summary,
                input_fingerprint=state.contract_content_fingerprint(),
                output_fingerprint=(
                    projected_state.contract_content_fingerprint()
                    if projected_state is not None
                    else None
                ),
            )
            if any(finding.blocking for finding in findings):
                stop = not request.policy.continue_after_blocking_failure

    run_invariants = (
        not stop
        and _enabled(request, ValidationStage.INVARIANT)
        and (invariant_registry is not None or _invariants_required(request))
    )
    if run_invariants and invariant_registry is None:
        findings = (
            _pipeline_finding(
                ValidationStage.INVARIANT,
                ErrorCode.MISSING_INVARIANT_REGISTRY,
                f"{request.intent.value} requires an InvariantRegistry.",
            ),
        )
        stages[ValidationStage.INVARIANT] = _stage(
            ValidationStage.INVARIANT, executed=True, findings=findings
        )
        invalid_input = True
        stop = True
    elif run_invariants and invariant_registry is not None and state is not None:
        target = request.policy.invariant_target or _default_target(request.intent)
        selected_keys = _selection(
            request.selected_invariant_keys,
            request.policy.selected_invariant_keys,
            "selected_invariant_keys",
        )
        selected_scopes = _selection(
            request.selected_invariant_scopes,
            request.policy.selected_invariant_scopes,
            "selected_invariant_scopes",
        )
        targets: list[tuple[InvariantEvaluationTarget, ProjectState]] = []
        if target in {InvariantEvaluationTarget.ORIGINAL, InvariantEvaluationTarget.BOTH}:
            targets.append((InvariantEvaluationTarget.ORIGINAL, state))
        if target in {InvariantEvaluationTarget.PROJECTED, InvariantEvaluationTarget.BOTH}:
            if projected_state is not None:
                targets.append((InvariantEvaluationTarget.PROJECTED, projected_state))
            elif request.policy.prevent_projected_invariants_after_failed_projection:
                targets = []
            else:
                findings = (
                    _pipeline_finding(
                        ValidationStage.INVARIANT,
                        ErrorCode.VALIDATION_STAGE_FAILED,
                        "Projected-state invariant evaluation was requested without a projection.",
                    ),
                )
                stages[ValidationStage.INVARIANT] = _stage(
                    ValidationStage.INVARIANT, executed=True, findings=findings
                )
                targets = []
        if targets:
            invariant_findings: tuple[ValidationFinding, ...] = ()
            evaluated_count = 0
            skipped_count = 0
            input_fingerprints: list[str] = []
            try:
                for target_name, target_state in targets:
                    context = InvariantEvaluationContext(
                        state=target_state,
                        evaluated_at=request.evaluated_at,
                        history=request.event_history,
                        previous_snapshots=request.previous_snapshots,
                        selected_keys=selected_keys,
                        selected_scopes=selected_scopes,
                    )
                    result = evaluate_invariants(context, invariant_registry)
                    invariant_findings += normalize_invariant_result(
                        result,
                        target=target_name,
                        start_sequence=1 + len(invariant_findings),
                    )
                    evaluated_count += len(result.evaluated_invariant_ids)
                    skipped_count += len(result.skipped_invariant_ids)
                    input_fingerprints.append(result.input_fingerprint)
                invariant_summary = {
                    "target": target.value,
                    "evaluated": evaluated_count,
                    "skipped": skipped_count,
                }
                stages[ValidationStage.INVARIANT] = _stage(
                    ValidationStage.INVARIANT,
                    executed=True,
                    findings=invariant_findings,
                    metadata=invariant_summary,
                    input_fingerprint=compute_fingerprint(input_fingerprints),
                    output_fingerprint=compute_fingerprint(
                        tuple(finding.model_dump(mode="json") for finding in invariant_findings)
                    ),
                )
            except ArchKernelError as error:
                findings = normalize_error_details(
                    (error.detail,),
                    stage=ValidationStage.INVARIANT,
                    kind=ValidationFindingKind.PIPELINE_ERROR,
                )
                stages[ValidationStage.INVARIANT] = _stage(
                    ValidationStage.INVARIANT, executed=True, findings=findings
                )

    stages[ValidationStage.FINALIZATION] = _stage(
        ValidationStage.FINALIZATION,
        executed=True,
        metadata={"canonical_stage_count": len(ValidationStage)},
    )
    ordered = _resequence(tuple(stages[stage] for stage in ValidationStage))
    findings = tuple(finding for stage in ordered for finding in stage.findings)
    disposition = _disposition(
        findings,
        ordered,
        invalid_input=invalid_input,
        non_blocking_affects=request.policy.non_blocking_findings_affect_disposition,
    )
    counts_by_stage = _counts(findings, "stage", tuple(ValidationStage))
    counts_by_severity = _counts(findings, "severity", tuple(Severity))
    counts_by_kind = _counts(findings, "kind", tuple(ValidationFindingKind))
    exposed_patch = generated_patch if request.policy.expose_transition_outputs else None
    exposed_projected = projected_state
    if request.intent is ValidationIntent.VALIDATE_TRANSITION and not (
        request.policy.expose_transition_outputs
    ):
        exposed_projected = None
    values = {
        "intent": request.intent,
        "disposition": disposition,
        "success": not any(finding.blocking for finding in findings),
        "blocking_failure": any(finding.blocking for finding in findings),
        "contract_stage": ordered[0],
        "aggregate_stage": ordered[1],
        "patch_stage": ordered[2],
        "transition_stage": ordered[3],
        "invariant_stage": ordered[4],
        "finalization_stage": ordered[5],
        "findings": findings,
        "counts_by_stage": counts_by_stage,
        "counts_by_severity": counts_by_severity,
        "counts_by_kind": counts_by_kind,
        "evaluated_at": request.evaluated_at,
        "validated_state": state,
        "generated_patch": exposed_patch,
        "projected_state": exposed_projected,
        "transition_summary": (
            freeze_json_object(transition_summary) if transition_summary is not None else None
        ),
        "invariant_summary": (
            freeze_json_object(invariant_summary) if invariant_summary is not None else None
        ),
        "input_fingerprint": input_fingerprint,
        "result_fingerprint": _ZERO_FINGERPRINT,
    }
    provisional = ValidationPipelineResult.model_validate(values)
    semantic_result = _strip_volatile(
        provisional.model_dump(mode="json", exclude={"result_fingerprint"})
    )
    return provisional.model_copy(
        update={"result_fingerprint": compute_fingerprint(semantic_result)}
    )


__all__ = ("run_validation_pipeline",)
