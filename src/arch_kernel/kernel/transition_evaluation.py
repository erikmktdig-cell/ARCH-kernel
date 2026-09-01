"""Pure deterministic evaluation of WP-K06 declarative transitions."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from arch_kernel.contracts.artifacts import ArtifactRecord
from arch_kernel.contracts.base import ContractModel
from arch_kernel.contracts.enums import ExecutionStatus, PhaseStatus
from arch_kernel.contracts.events import ActorType, EventActor
from arch_kernel.contracts.ids import (
    ArtifactId,
    DecisionId,
    PatchId,
    PhaseId,
    ProjectId,
    RequirementId,
    RiskId,
    WorkflowId,
)
from arch_kernel.contracts.lifecycle import PhaseExecutionRecord
from arch_kernel.contracts.patches import (
    DryRunResult,
    PatchOperation,
    PatchOperationType,
    PatchPath,
    StatePatch,
)
from arch_kernel.contracts.project_state import ProjectState
from arch_kernel.contracts.references import TypedReference
from arch_kernel.contracts.requirements import RequirementRecord
from arch_kernel.contracts.risks import RiskRecord
from arch_kernel.contracts.transitions import (
    EffectType,
    EffectValueSource,
    GuardEvaluation,
    GuardType,
    TransitionDefinition,
    TransitionDomain,
    TransitionEffect,
    TransitionEvaluationResult,
    TransitionGuard,
    TransitionRequest,
    TransitionTarget,
    WorkflowTransitionDefinition,
)
from arch_kernel.contracts.workflows import WorkflowStateRecord
from arch_kernel.kernel.errors import ErrorCode, ErrorDetail, Severity
from arch_kernel.kernel.event_validation import FrozenJsonValue, thaw_json
from arch_kernel.kernel.fingerprints import canonicalize_json
from arch_kernel.kernel.patch_application import apply_state_patch_dry_run
from arch_kernel.kernel.path_policy import validate_patch_path_policy
from arch_kernel.kernel.time import ensure_utc
from arch_kernel.kernel.transition_registry import TransitionRegistry

_MISSING = object()
_SATISFIED_STATES = frozenset(
    {
        "accepted",
        "approved",
        "conditionally_approved",
        "completed",
        "completed_with_conditions",
        "implemented",
        "verified",
        "closed",
    }
)


def _error(
    code: ErrorCode,
    message: str,
    *,
    path: tuple[str | int, ...] = (),
    entity_type: str = "transition",
    entity_id: str | None = None,
    expected: str | int | None = None,
    actual: str | int | None = None,
    remediation_hint: str | None = None,
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
        severity=Severity.ERROR,
    )


def _denied(
    errors: tuple[ErrorDetail, ...],
    *,
    transition: TransitionDefinition | None = None,
    current_state: str | None = None,
    guards: tuple[GuardEvaluation, ...] = (),
    state_patch: StatePatch | None = None,
    dry_run_result: DryRunResult | None = None,
) -> TransitionEvaluationResult:
    return TransitionEvaluationResult(
        allowed=False,
        transition=transition,
        current_state=current_state,
        target_state=None if transition is None else transition.to_state,
        guard_evaluations=guards,
        state_patch=state_patch,
        dry_run_result=dry_run_result,
        errors=errors,
    )


def _resolve_record(state: ProjectState, target: TransitionTarget) -> ContractModel | None:
    entity_id = target.entity_id
    if target.domain is TransitionDomain.PROJECT_LIFECYCLE:
        return state if entity_id == state.metadata.project_id else None
    if target.domain is TransitionDomain.PHASE_STATUS and isinstance(entity_id, PhaseId):
        return state.phase_execution_records.get(entity_id)
    if target.domain is TransitionDomain.ARTIFACT_STATUS and isinstance(entity_id, ArtifactId):
        return state.artifact_registry.get(entity_id)
    if target.domain is TransitionDomain.RISK_STATUS and isinstance(entity_id, RiskId):
        return state.risk_registry.get(entity_id)
    if target.domain is TransitionDomain.REQUIREMENT_STATUS and isinstance(
        entity_id, RequirementId
    ):
        return state.requirement_registry.get(entity_id)
    if target.domain is TransitionDomain.WORKFLOW_STATE and isinstance(entity_id, WorkflowId):
        return state.workflow_registry.get(entity_id)
    return None


def _resolve_current_state(
    state: ProjectState, target: TransitionTarget
) -> tuple[str | None, ContractModel | None]:
    record = _resolve_record(state, target)
    if record is None:
        return None, None
    if target.domain is TransitionDomain.PROJECT_LIFECYCLE:
        return state.lifecycle.status.value, state
    if isinstance(record, PhaseExecutionRecord):
        return record.status.value, record
    if isinstance(record, ArtifactRecord):
        return record.status.value, record
    if isinstance(record, (RiskRecord, RequirementRecord)):
        return record.status, record
    if isinstance(record, WorkflowStateRecord):
        return str(record.current_state), record
    return None, record


def _public_document(state: ProjectState) -> dict[str, object]:
    return {
        "metadata": state.metadata.model_dump(mode="json"),
        "profile": state.profile.model_dump(mode="json"),
        "lifecycle": state.lifecycle.model_dump(mode="json"),
        "phases": {
            str(key): value.model_dump(mode="json")
            for key, value in state.phase_execution_records.items()
        },
        "artifacts": {
            str(key): value.model_dump(mode="json")
            for key, value in state.artifact_registry.items()
        },
        "requirements": {
            str(key): value.model_dump(mode="json")
            for key, value in state.requirement_registry.items()
        },
        "risks": {
            str(key): value.model_dump(mode="json") for key, value in state.risk_registry.items()
        },
        "workflows": {
            str(key): value.model_dump(mode="json")
            for key, value in state.workflow_registry.items()
        },
        "decisions": {
            str(value.decision_id): value.model_dump(mode="json") for value in state.decision_log
        },
        "dependencies": [value.model_dump(mode="json") for value in state.dependency_graph],
    }


def _read_path(state: ProjectState, path: PatchPath) -> object:
    current: object = _public_document(state)
    for segment in path.segments:
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        elif isinstance(current, list) and segment.isdigit():
            index = int(segment)
            if index >= len(current):
                return _MISSING
            current = current[index]
        else:
            return _MISSING
    return current


def _reference_exists(state: ProjectState, reference: TypedReference) -> bool:
    target_id = reference.target_id
    if isinstance(target_id, ProjectId):
        return target_id == state.metadata.project_id
    if isinstance(target_id, PhaseId):
        return target_id in state.phase_execution_records
    if isinstance(target_id, ArtifactId):
        return target_id in state.artifact_registry
    if isinstance(target_id, RequirementId):
        return target_id in state.requirement_registry
    if isinstance(target_id, RiskId):
        return target_id in state.risk_registry
    if isinstance(target_id, WorkflowId):
        return target_id in state.workflow_registry
    if isinstance(target_id, DecisionId):
        return any(item.decision_id == target_id for item in state.decision_log)
    return False


def _reference_status(state: ProjectState, reference: TypedReference) -> str | None:
    target_id = reference.target_id
    if isinstance(target_id, PhaseId):
        phase = state.phase_execution_records.get(target_id)
        return None if phase is None else phase.status.value
    if isinstance(target_id, ArtifactId):
        artifact = state.artifact_registry.get(target_id)
        return None if artifact is None else artifact.status.value
    if isinstance(target_id, RequirementId):
        requirement = state.requirement_registry.get(target_id)
        return None if requirement is None else requirement.status
    if isinstance(target_id, RiskId):
        risk = state.risk_registry.get(target_id)
        return None if risk is None else risk.status
    if isinstance(target_id, WorkflowId):
        workflow = state.workflow_registry.get(target_id)
        return None if workflow is None else str(workflow.current_state)
    if isinstance(target_id, DecisionId):
        decision = next(
            (item for item in state.decision_log if item.decision_id == target_id),
            None,
        )
        return None if decision is None else decision.status
    return None


def _all_dependencies_satisfied(state: ProjectState, target: TransitionTarget) -> bool:
    relevant = tuple(
        edge
        for edge in state.dependency_graph
        if edge.required
        and edge.dependency_type == "requires"
        and edge.source.target_id == target.entity_id
    )
    return all(_reference_status(state, edge.target) in _SATISFIED_STATES for edge in relevant)


def _guard_error(guard: TransitionGuard, actual: object) -> ErrorDetail:
    return _error(
        ErrorCode.TRANSITION_GUARD_FAILED,
        guard.message or f"Transition guard {guard.guard_type.value} failed.",
        path=() if guard.path is None else ("guards", str(guard.path)),
        expected=guard.guard_type.value,
        actual="missing" if actual is _MISSING else str(actual),
        remediation_hint="Satisfy the declared guard before retrying the transition.",
    )


def _evaluate_guard(
    state: ProjectState, target: TransitionTarget, guard: TransitionGuard
) -> GuardEvaluation:
    actual: object = None
    passed = False
    if guard.guard_type in {
        GuardType.FIELD_EQUALS,
        GuardType.FIELD_NOT_EQUALS,
        GuardType.FIELD_IN,
        GuardType.FIELD_EXISTS,
        GuardType.FIELD_ABSENT,
    }:
        if guard.path is None:  # pragma: no cover - contract validation guarantees this
            raise AssertionError("Field guard has no path.")
        actual = _read_path(state, guard.path)
        if guard.guard_type is GuardType.FIELD_EXISTS:
            passed = actual is not _MISSING
        elif guard.guard_type is GuardType.FIELD_ABSENT:
            passed = actual is _MISSING
        elif actual is not _MISSING:
            if guard.guard_type is GuardType.FIELD_EQUALS:
                passed = canonicalize_json(actual) == canonicalize_json(thaw_json(guard.expected))
            elif guard.guard_type is GuardType.FIELD_NOT_EQUALS:
                passed = canonicalize_json(actual) != canonicalize_json(thaw_json(guard.expected))
            else:
                passed = any(
                    canonicalize_json(actual) == canonicalize_json(thaw_json(value))
                    for value in guard.allowed_values
                )
    elif guard.guard_type is GuardType.REFERENCE_EXISTS:
        if guard.reference is None:  # pragma: no cover - contract validation guarantees this
            raise AssertionError("Reference guard has no reference.")
        actual = str(guard.reference.target_id)
        passed = _reference_exists(state, guard.reference)
    elif guard.guard_type is GuardType.NO_ACTIVE_PHASE_EXCEPT_TARGET:
        active_ids = tuple(
            phase_id
            for phase_id, record in state.phase_execution_records.items()
            if record.status is PhaseStatus.ACTIVE and phase_id != target.entity_id
        )
        actual = tuple(str(item) for item in active_ids)
        passed = not active_ids
    else:
        actual = _all_dependencies_satisfied(state, target)
        passed = bool(actual)
    error = None if passed else _guard_error(guard, actual)
    serializable_actual: FrozenJsonValue | None
    if actual is _MISSING:
        serializable_actual = None
    elif isinstance(actual, tuple):
        serializable_actual = cast(FrozenJsonValue, list(actual))
    else:
        serializable_actual = cast(FrozenJsonValue, actual)
    return GuardEvaluation(
        guard=guard,
        passed=passed,
        actual=serializable_actual,
        error=error,
    )


def _render_path(
    effect: TransitionEffect,
    request: TransitionRequest,
    transition: TransitionDefinition,
    evaluated_at: datetime,
) -> PatchPath:
    values = {
        "{project_id}": str(request.project_id),
        "{entity_id}": str(request.target.entity_id),
        "{evaluated_at}": evaluated_at.isoformat().replace("+00:00", "Z"),
        "{to_state}": transition.to_state,
    }
    rendered = effect.path_template
    for placeholder, value in values.items():
        rendered = rendered.replace(placeholder, value)
    return PatchPath.parse(rendered)


def _effect_value(
    effect: TransitionEffect,
    request: TransitionRequest,
    transition: TransitionDefinition,
    evaluated_at: datetime,
) -> object:
    if effect.value_source is EffectValueSource.LITERAL:
        return thaw_json(effect.literal_value)
    if effect.value_source is EffectValueSource.TO_STATE:
        return transition.to_state
    if effect.value_source is EffectValueSource.EVALUATED_AT:
        return evaluated_at.isoformat().replace("+00:00", "Z")
    if effect.value_source is EffectValueSource.ENTITY_ID:
        return str(request.target.entity_id)
    raise AssertionError("Effect without a value cannot be rendered.")


def _render_operations(
    transition: TransitionDefinition,
    request: TransitionRequest,
    evaluated_at: datetime,
) -> tuple[PatchOperation, ...]:
    operation_types = {
        EffectType.SET_FIELD: PatchOperationType.REPLACE,
        EffectType.REMOVE_FIELD: PatchOperationType.REMOVE,
        EffectType.ASSERT_FIELD: PatchOperationType.TEST,
    }
    operations: list[PatchOperation] = []
    mutation_paths: set[PatchPath] = set()
    for effect in transition.effects:
        path = _render_path(effect, request, transition, evaluated_at)
        operation_type = operation_types[effect.effect_type]
        policy_error = validate_patch_path_policy(path, operation_type)
        if policy_error is not None:
            raise ValueError(policy_error.message)
        if operation_type is not PatchOperationType.TEST:
            if path in mutation_paths:
                raise ValueError("Effects render duplicate mutation paths.")
            mutation_paths.add(path)
        fields: dict[str, object] = {"op": operation_type, "path": path}
        if operation_type is not PatchOperationType.REMOVE:
            fields["value"] = _effect_value(effect, request, transition, evaluated_at)
        if request.target.domain is not TransitionDomain.PROJECT_LIFECYCLE:
            fields["expected_record_version"] = request.expected_target_record_version
            fields["expected_content_fingerprint"] = request.expected_target_content_fingerprint
        operations.append(PatchOperation.model_validate(fields))
    return tuple(operations)


def _scope_for_target(target: TransitionTarget) -> PatchPath:
    if target.domain is TransitionDomain.PROJECT_LIFECYCLE:
        return PatchPath.parse("/lifecycle")
    roots = {
        TransitionDomain.PHASE_STATUS: "phases",
        TransitionDomain.ARTIFACT_STATUS: "artifacts",
        TransitionDomain.RISK_STATUS: "risks",
        TransitionDomain.REQUIREMENT_STATUS: "requirements",
        TransitionDomain.WORKFLOW_STATE: "workflows",
    }
    root = roots[target.domain]
    return PatchPath.parse(f"/{root}/{target.entity_id}")


def _build_patch(
    state: ProjectState,
    request: TransitionRequest,
    transition: TransitionDefinition,
    operations: tuple[PatchOperation, ...],
) -> StatePatch:
    patch_id = PatchId.from_str(f"PATCH-{request.request_id.ulid}")
    actor = EventActor(
        contract_name="event_actor",
        contract_version=transition.contract_version,
        schema_uri="urn:arch:contracts:event_actor:1.0.0",
        created_at=request.requested_at,
        actor_type=ActorType.SYSTEM,
        actor_id="arch-kernel.transition-evaluator",
        display_name="ARch transition evaluator",
    )
    return StatePatch(
        contract_name="state_patch",
        contract_version=transition.contract_version,
        schema_uri="urn:arch:contracts:state_patch:1.0.0",
        created_at=request.requested_at,
        patch_id=patch_id,
        project_id=request.project_id,
        base_state_record_version=(
            state.record_version
            if request.base_state_record_version is None
            else request.base_state_record_version
        ),
        base_state_content_fingerprint=(
            state.contract_content_fingerprint()
            if request.expected_state_content_fingerprint is None
            else request.expected_state_content_fingerprint
        ),
        operations=operations,
        created_by=actor,
        reason=f"Evaluate transition {transition.transition_key}.",
        scope=(_scope_for_target(request.target),),
    )


def evaluate_transition(
    state: ProjectState,
    request: TransitionRequest,
    registry: TransitionRegistry,
    *,
    evaluated_at: datetime | None = None,
) -> TransitionEvaluationResult:
    """Resolve and purely evaluate one transition through the K05 dry-run engine."""

    evaluation_time = ensure_utc(evaluated_at or request.requested_at)
    if request.project_id != state.metadata.project_id:
        return _denied(
            (
                _error(
                    ErrorCode.INVALID_REFERENCE,
                    "Transition request project does not match ProjectState.",
                    path=("project_id",),
                    expected=str(state.metadata.project_id),
                    actual=str(request.project_id),
                ),
            )
        )
    transition = (
        registry.get_by_id(request.transition_id)
        if request.transition_id is not None
        else registry.get_by_key(cast(str, request.transition_key))
    )
    if transition is None:
        selector = (
            str(request.transition_id)
            if request.transition_id is not None
            else cast(str, request.transition_key)
        )
        return _denied(
            (
                _error(
                    ErrorCode.TRANSITION_NOT_FOUND,
                    "Transition selector was not found in the registry.",
                    path=("transition_id",)
                    if request.transition_id is not None
                    else ("transition_key",),
                    actual=selector,
                ),
            )
        )
    if transition.domain is not request.target.domain:
        return _denied(
            (
                _error(
                    ErrorCode.INVALID_REFERENCE,
                    "Transition domain does not match the target domain.",
                    expected=transition.domain.value,
                    actual=request.target.domain.value,
                ),
            ),
            transition=transition,
        )
    if request.target.domain is TransitionDomain.WORKFLOW_STATE and not isinstance(
        transition, WorkflowTransitionDefinition
    ):
        return _denied(
            (
                _error(
                    ErrorCode.INVALID_TRANSITION_DEFINITION,
                    "Workflow target requires a workflow-bound transition definition.",
                ),
            ),
            transition=transition,
        )
    current_state, target_record = _resolve_current_state(state, request.target)
    if current_state is None or target_record is None:
        return _denied(
            (
                _error(
                    ErrorCode.INVALID_REFERENCE,
                    "Transition target does not exist in ProjectState.",
                    entity_id=str(request.target.entity_id),
                    expected=request.target.domain.value,
                    actual="missing",
                ),
            ),
            transition=transition,
        )
    if isinstance(transition, WorkflowTransitionDefinition):
        if not isinstance(target_record, WorkflowStateRecord):
            return _denied(
                (
                    _error(
                        ErrorCode.INVALID_REFERENCE,
                        "Workflow transition target is not a workflow state record.",
                    ),
                ),
                transition=transition,
            )
        workflow_definition = registry.workflow_definitions.get(
            transition.workflow_namespace,
            transition.workflow_definition_version,
        )
        definition_matches = (
            workflow_definition is not None
            and target_record.namespace == transition.workflow_namespace
            and target_record.definition_version == transition.workflow_definition_version
            and target_record.definition_fingerprint == transition.workflow_definition_fingerprint
            and current_state in tuple(str(item) for item in workflow_definition.allowed_states)
        )
        if not definition_matches:
            return _denied(
                (
                    _error(
                        ErrorCode.INVALID_REFERENCE,
                        "Workflow record does not match the transition state space.",
                        expected=str(transition.workflow_namespace),
                        actual=str(target_record.namespace),
                    ),
                ),
                transition=transition,
                current_state=current_state,
            )
        if (
            request.expected_target_record_version is None
            or request.expected_target_content_fingerprint is None
        ):
            return _denied(
                (
                    _error(
                        ErrorCode.STALE_OBJECT_VERSION,
                        "Workflow transitions require exact target version and fingerprint.",
                        expected="record version and content fingerprint",
                        actual="missing precondition",
                    ),
                ),
                transition=transition,
                current_state=current_state,
            )
    if current_state not in transition.from_states:
        return _denied(
            (
                _error(
                    ErrorCode.INVALID_TRANSITION_DEFINITION,
                    "Current state is not admitted by the transition.",
                    expected=", ".join(transition.from_states),
                    actual=current_state,
                ),
            ),
            transition=transition,
            current_state=current_state,
        )
    if request.expected_from_state is not None and request.expected_from_state != current_state:
        return _denied(
            (
                _error(
                    ErrorCode.STALE_OBJECT_VERSION,
                    "Transition expected_from_state is stale.",
                    path=("expected_from_state",),
                    expected=current_state,
                    actual=request.expected_from_state,
                ),
            ),
            transition=transition,
            current_state=current_state,
        )
    if request.target.domain is TransitionDomain.PROJECT_LIFECYCLE:
        if (
            request.expected_target_record_version is not None
            and request.expected_target_record_version != state.record_version
        ):
            return _denied(
                (
                    _error(
                        ErrorCode.STALE_OBJECT_VERSION,
                        "Project lifecycle target version is stale.",
                        expected=state.record_version,
                        actual=request.expected_target_record_version,
                    ),
                ),
                transition=transition,
                current_state=current_state,
            )
        if (
            request.expected_target_content_fingerprint is not None
            and request.expected_target_content_fingerprint != state.contract_content_fingerprint()
        ):
            return _denied(
                (
                    _error(
                        ErrorCode.STALE_OBJECT_VERSION,
                        "Project lifecycle target fingerprint is stale.",
                        expected=state.contract_content_fingerprint(),
                        actual=request.expected_target_content_fingerprint,
                    ),
                ),
                transition=transition,
                current_state=current_state,
            )

    guard_results = tuple(
        _evaluate_guard(state, request.target, guard) for guard in transition.guards
    )
    guard_errors = tuple(result.error for result in guard_results if result.error is not None)
    if guard_errors:
        return _denied(
            guard_errors,
            transition=transition,
            current_state=current_state,
            guards=guard_results,
        )
    try:
        operations = _render_operations(transition, request, evaluation_time)
        state_patch = _build_patch(state, request, transition, operations)
    except (TypeError, ValueError) as error:
        return _denied(
            (
                _error(
                    ErrorCode.INVALID_TRANSITION_DEFINITION,
                    "Transition effects could not produce a valid K05 patch.",
                    actual=str(error),
                ),
            ),
            transition=transition,
            current_state=current_state,
            guards=guard_results,
        )
    dry_run = apply_state_patch_dry_run(
        state,
        state_patch,
        evaluated_at=evaluation_time,
    )
    if dry_run.status is not ExecutionStatus.COMPLETED:
        return _denied(
            dry_run.validation.errors,
            transition=transition,
            current_state=current_state,
            guards=guard_results,
            state_patch=state_patch,
            dry_run_result=dry_run,
        )
    return TransitionEvaluationResult(
        allowed=True,
        transition=transition,
        current_state=current_state,
        target_state=transition.to_state,
        guard_evaluations=guard_results,
        state_patch=state_patch,
        dry_run_result=dry_run,
        errors=(),
    )


__all__ = ("evaluate_transition",)
