"""Pure deterministic evaluation for the nine canonical K07 invariants."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from itertools import pairwise
from types import MappingProxyType

from arch_kernel.contracts.artifacts import ArtifactRecord
from arch_kernel.contracts.base import ContractModel, VersionedRecord
from arch_kernel.contracts.decisions import DecisionRecord
from arch_kernel.contracts.enums import ArtifactStatus, PhaseStatus
from arch_kernel.contracts.ids import (
    ArtifactId,
    DecisionId,
    PhaseId,
    ProjectId,
    RequirementId,
    RiskId,
)
from arch_kernel.contracts.invariants import (
    InvariantDefinition,
    InvariantEvaluationContext,
    InvariantEvaluationResult,
    InvariantEvidence,
    InvariantKind,
    InvariantSeverity,
    InvariantViolation,
)
from arch_kernel.contracts.lifecycle import PhaseExecutionRecord
from arch_kernel.contracts.project_state import ProjectState
from arch_kernel.contracts.references import TypedReference
from arch_kernel.contracts.requirements import RequirementRecord
from arch_kernel.contracts.risks import RiskRecord
from arch_kernel.kernel.errors import ArchKernelError, ErrorCode, ErrorDetail, Severity
from arch_kernel.kernel.event_validation import freeze_json_object, thaw_json
from arch_kernel.kernel.fingerprints import compute_fingerprint
from arch_kernel.kernel.invariant_registry import InvariantRegistry

_LIFECYCLE_COMPATIBILITY: Mapping[str, frozenset[str]] = MappingProxyType(
    {status.value: frozenset({status.value}) for status in PhaseStatus}
)
_DEFAULT_SOURCE_TERMINAL_STATES: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "phase": frozenset({"completed", "completed_with_conditions"}),
        "artifact": frozenset({"approved", "conditionally_approved", "superseded", "archived"}),
        "requirement": frozenset({"implemented", "verified"}),
        "risk": frozenset({"accepted", "closed"}),
        "decision": frozenset({"accepted", "superseded"}),
    }
)
_DEFAULT_TARGET_SATISFIED_STATES: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "phase": frozenset({"completed", "completed_with_conditions"}),
        "artifact": frozenset({"approved", "conditionally_approved"}),
        "requirement": frozenset({"accepted", "implemented", "verified"}),
        "risk": frozenset({"accepted", "closed"}),
        "decision": frozenset({"accepted"}),
    }
)

type _Evaluator = Callable[
    [InvariantDefinition, InvariantEvaluationContext],
    tuple[InvariantViolation, ...],
]


def _configuration(definition: InvariantDefinition) -> Mapping[str, object]:
    value = thaw_json(definition.configuration)
    if not isinstance(value, dict):
        raise TypeError("Invariant configuration must be a JSON object.")
    return value


def _typed_reference(identifier: object) -> TypedReference | None:
    if isinstance(identifier, ProjectId):
        return TypedReference(target_type="project", target_id=identifier)
    if isinstance(identifier, PhaseId):
        return TypedReference(target_type="phase", target_id=identifier)
    if isinstance(identifier, ArtifactId):
        return TypedReference(target_type="artifact", target_id=identifier)
    if isinstance(identifier, RequirementId):
        return TypedReference(target_type="requirement", target_id=identifier)
    if isinstance(identifier, RiskId):
        return TypedReference(target_type="risk", target_id=identifier)
    if isinstance(identifier, DecisionId):
        return TypedReference(target_type="decision", target_id=identifier)
    return None


def _evidence(
    *,
    path: str,
    observed: object,
    expected: object,
    identifier: object | None = None,
    message: str | None = None,
) -> InvariantEvidence:
    return InvariantEvidence.model_validate(
        {
            "reference": None if identifier is None else _typed_reference(identifier),
            "path": path,
            "observed": observed,
            "expected": expected,
            "message": message,
        }
    )


def _violation(
    definition: InvariantDefinition,
    message: str,
    evidence: tuple[InvariantEvidence, ...],
) -> InvariantViolation:
    return InvariantViolation(
        invariant_id=definition.invariant_id,
        key=definition.key,
        kind=definition.kind,
        scope=definition.scope,
        severity=definition.severity,
        blocking=definition.blocking,
        message=message,
        evidence=evidence,
        remediation_hint=definition.remediation_hint,
    )


def _single_active_phase(
    definition: InvariantDefinition,
    context: InvariantEvaluationContext,
) -> tuple[InvariantViolation, ...]:
    active = tuple(
        sorted(
            (
                phase_id
                for phase_id, record in context.state.phase_execution_records.items()
                if record.status is PhaseStatus.ACTIVE
            ),
            key=str,
        )
    )
    if len(active) <= 1:
        return ()
    evidence = tuple(
        _evidence(
            path=f"/phases/{phase_id}/status",
            observed="active",
            expected="at most one active phase",
            identifier=phase_id,
        )
        for phase_id in active
    )
    return (
        _violation(
            definition,
            "More than one phase is active.",
            evidence,
        ),
    )


def _lifecycle_phase_alignment(
    definition: InvariantDefinition,
    context: InvariantEvaluationContext,
) -> tuple[InvariantViolation, ...]:
    lifecycle = context.state.lifecycle
    phase_id = lifecycle.current_phase_id
    if phase_id is None:
        return ()
    phase = context.state.phase_execution_records.get(phase_id)
    if phase is None:
        return (
            _violation(
                definition,
                "Lifecycle current phase is absent from the phase registry.",
                (
                    _evidence(
                        path="/lifecycle/current_phase_id",
                        observed=str(phase_id),
                        expected="existing PhaseId",
                        identifier=phase_id,
                    ),
                ),
            ),
        )
    allowed = _LIFECYCLE_COMPATIBILITY[lifecycle.status.value]
    evidence: list[InvariantEvidence] = []
    if phase.status.value not in allowed:
        evidence.append(
            _evidence(
                path=f"/phases/{phase_id}/status",
                observed=phase.status.value,
                expected=sorted(allowed),
                identifier=phase_id,
            )
        )
    if phase.phase_code != lifecycle.current_phase_code:
        evidence.append(
            _evidence(
                path=f"/phases/{phase_id}/phase_code",
                observed=phase.phase_code.value,
                expected=None
                if lifecycle.current_phase_code is None
                else lifecycle.current_phase_code.value,
                identifier=phase_id,
            )
        )
    if not evidence:
        return ()
    return (
        _violation(
            definition,
            "Lifecycle and current phase are not aligned.",
            tuple(evidence),
        ),
    )


def _approved_baseline_integrity(
    definition: InvariantDefinition,
    context: InvariantEvaluationContext,
) -> tuple[InvariantViolation, ...]:
    configuration = _configuration(definition)
    allowed = _configured_strings(
        configuration,
        "allowed_statuses",
        (
            ArtifactStatus.APPROVED.value,
            ArtifactStatus.CONDITIONALLY_APPROVED.value,
        ),
    )
    require_fingerprint = configuration.get("require_content_fingerprint", False) is True
    violations: list[InvariantViolation] = []
    ordered_baselines = sorted(
        enumerate(context.state.active_baseline_artifact_ids),
        key=lambda item: str(item[1]),
    )
    for index, artifact_id in ordered_baselines:
        artifact = context.state.artifact_registry.get(artifact_id)
        evidence: list[InvariantEvidence] = []
        if artifact is None:
            evidence.append(
                _evidence(
                    path=f"/active_baseline_artifact_ids/{index}",
                    observed=str(artifact_id),
                    expected="existing artifact",
                    identifier=artifact_id,
                )
            )
        else:
            if artifact.status.value not in allowed:
                evidence.append(
                    _evidence(
                        path=f"/artifacts/{artifact_id}/status",
                        observed=artifact.status.value,
                        expected=sorted(allowed),
                        identifier=artifact_id,
                    )
                )
            if require_fingerprint and artifact.content_fingerprint is None:
                evidence.append(
                    _evidence(
                        path=f"/artifacts/{artifact_id}/content_fingerprint",
                        observed=None,
                        expected="sha256 content fingerprint",
                        identifier=artifact_id,
                    )
                )
        if evidence:
            violations.append(
                _violation(
                    definition,
                    "Active baseline artifact does not satisfy integrity policy.",
                    tuple(evidence),
                )
            )
    return tuple(violations)


def _reference_record(
    state: ProjectState,
    reference: TypedReference,
) -> ContractModel | None:
    target_id = reference.target_id
    if isinstance(target_id, ProjectId):
        return state if target_id == state.metadata.project_id else None
    if isinstance(target_id, PhaseId):
        return state.phase_execution_records.get(target_id)
    if isinstance(target_id, ArtifactId):
        return state.artifact_registry.get(target_id)
    if isinstance(target_id, RequirementId):
        return state.requirement_registry.get(target_id)
    if isinstance(target_id, RiskId):
        return state.risk_registry.get(target_id)
    if isinstance(target_id, DecisionId):
        return next(
            (record for record in state.decision_log if record.decision_id == target_id),
            None,
        )
    return None


def _record_status(record: ContractModel | None) -> str | None:
    if isinstance(record, PhaseExecutionRecord):
        return record.status.value
    if isinstance(record, ArtifactRecord):
        return record.status.value
    if isinstance(record, (RequirementRecord, RiskRecord, DecisionRecord)):
        return record.status
    return None


def _configured_strings(
    configuration: Mapping[str, object],
    key: str,
    default: tuple[str, ...],
) -> frozenset[str]:
    value = configuration.get(key)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return frozenset(value)
    return frozenset(default)


def _configured_state_mapping(
    configuration: Mapping[str, object],
    key: str,
    default: Mapping[str, frozenset[str]],
) -> Mapping[str, frozenset[str]]:
    configured = configuration.get(key)
    if not isinstance(configured, dict):
        return default
    return MappingProxyType(
        {
            target_type: frozenset(states)
            for target_type, states in configured.items()
            if isinstance(target_type, str) and isinstance(states, list)
        }
    )


def _required_dependency_satisfaction(
    definition: InvariantDefinition,
    context: InvariantEvaluationContext,
) -> tuple[InvariantViolation, ...]:
    configuration = _configuration(definition)
    source_terminal = _configured_state_mapping(
        configuration,
        "source_terminal_states",
        _DEFAULT_SOURCE_TERMINAL_STATES,
    )
    target_satisfied = _configured_state_mapping(
        configuration,
        "target_satisfied_states",
        _DEFAULT_TARGET_SATISFIED_STATES,
    )
    violations: list[InvariantViolation] = []
    ordered_edges = sorted(
        enumerate(context.state.dependency_graph),
        key=lambda item: (
            str(item[1].source.target_id),
            str(item[1].target.target_id),
            item[1].dependency_type,
            item[0],
        ),
    )
    for index, edge in ordered_edges:
        if not edge.required or edge.dependency_type != "requires":
            continue
        source_status = _record_status(_reference_record(context.state, edge.source))
        target_status = _record_status(_reference_record(context.state, edge.target))
        terminal_states = source_terminal.get(edge.source.target_type, frozenset())
        satisfied_states = target_satisfied.get(edge.target.target_type, frozenset())
        if source_status not in terminal_states or target_status in satisfied_states:
            continue
        violations.append(
            _violation(
                definition,
                "A terminal source has an unsatisfied mandatory dependency.",
                (
                    _evidence(
                        path=f"/dependencies/{index}/source",
                        observed=source_status,
                        expected=sorted(terminal_states),
                        identifier=edge.source.target_id,
                    ),
                    _evidence(
                        path=f"/dependencies/{index}/target",
                        observed=target_status,
                        expected=sorted(satisfied_states),
                        identifier=edge.target.target_id,
                    ),
                ),
            )
        )
    return tuple(violations)


def _requirement_traceability(
    definition: InvariantDefinition,
    context: InvariantEvaluationContext,
) -> tuple[InvariantViolation, ...]:
    configuration = _configuration(definition)
    selected_statuses = _configured_strings(
        configuration,
        "statuses",
        ("accepted", "implemented", "verified"),
    )
    allowed_types = _configured_strings(
        configuration,
        "allowed_target_types",
        ("artifact", "decision"),
    )
    violations: list[InvariantViolation] = []
    for requirement_id, requirement in sorted(
        context.state.requirement_registry.items(), key=lambda item: str(item[0])
    ):
        if requirement.status not in selected_statuses:
            continue
        has_artifact_trace = "artifact" in allowed_types and any(
            artifact_id in context.state.artifact_registry
            for artifact_id in requirement.artifact_ids
        )
        has_edge_trace = any(
            (edge.source.target_id == requirement_id and edge.target.target_type in allowed_types)
            or (
                edge.target.target_id == requirement_id and edge.source.target_type in allowed_types
            )
            for edge in context.state.dependency_graph
        )
        if has_artifact_trace or has_edge_trace:
            continue
        violations.append(
            _violation(
                definition,
                "Requirement has no allowed aggregate-local trace.",
                (
                    _evidence(
                        path=f"/requirements/{requirement_id}/artifact_ids",
                        observed=[str(item) for item in requirement.artifact_ids],
                        expected=sorted(allowed_types),
                        identifier=requirement_id,
                    ),
                ),
            )
        )
    return tuple(violations)


def _critical_risk_control(
    definition: InvariantDefinition,
    context: InvariantEvaluationContext,
) -> tuple[InvariantViolation, ...]:
    configuration = _configuration(definition)
    threshold = configuration.get("score_threshold", 15)
    if type(threshold) is not int:
        raise TypeError("score_threshold must be an integer.")
    allowed_statuses = _configured_strings(
        configuration,
        "allowed_statuses",
        ("accepted", "closed"),
    )
    violations: list[InvariantViolation] = []
    for risk_id, risk in sorted(context.state.risk_registry.items(), key=lambda item: str(item[0])):
        controlled = risk.mitigation is not None or risk.status in allowed_statuses
        if risk.score < threshold or controlled:
            continue
        violations.append(
            _violation(
                definition,
                "Critical risk has no mitigation or allowed accepted status.",
                (
                    _evidence(
                        path=f"/risks/{risk_id}/score",
                        observed=risk.score,
                        expected=f"below {threshold} or controlled",
                        identifier=risk_id,
                    ),
                    _evidence(
                        path=f"/risks/{risk_id}/mitigation",
                        observed=risk.mitigation,
                        expected="non-empty mitigation or allowed status",
                        identifier=risk_id,
                    ),
                ),
            )
        )
    return tuple(violations)


def _terminal_phase_consistency(
    definition: InvariantDefinition,
    context: InvariantEvaluationContext,
) -> tuple[InvariantViolation, ...]:
    configuration = _configuration(definition)
    terminal_statuses = _configured_strings(
        configuration,
        "terminal_statuses",
        ("completed", "completed_with_conditions"),
    )
    require_completed_at = configuration.get("require_completed_at", True) is True
    require_outputs = configuration.get("require_outputs", False) is True
    violations: list[InvariantViolation] = []
    for phase_id, phase in sorted(
        context.state.phase_execution_records.items(), key=lambda item: str(item[0])
    ):
        if phase.status.value not in terminal_statuses:
            continue
        evidence: list[InvariantEvidence] = []
        if require_completed_at and phase.completed_at is None:
            evidence.append(
                _evidence(
                    path=f"/phases/{phase_id}/completed_at",
                    observed=None,
                    expected="UTC completion timestamp",
                    identifier=phase_id,
                )
            )
        if require_outputs and not phase.artifact_ids and not phase.requirement_ids:
            evidence.append(
                _evidence(
                    path=f"/phases/{phase_id}/artifact_ids",
                    observed=[],
                    expected="at least one artifact or requirement output",
                    identifier=phase_id,
                )
            )
        if evidence:
            violations.append(
                _violation(
                    definition,
                    "Terminal phase does not satisfy completion policy.",
                    tuple(evidence),
                )
            )
    return tuple(violations)


def _immutable_history_consistency(
    definition: InvariantDefinition,
    context: InvariantEvaluationContext,
) -> tuple[InvariantViolation, ...]:
    configuration = _configuration(definition)
    require_causation = configuration.get("require_causation_exists", True) is True
    seen_ids: dict[str, int] = {}
    seen_keys: dict[tuple[str, str, str], int] = {}
    violations: list[InvariantViolation] = []
    for index, event in enumerate(context.history):
        event_id = str(event.event_id)
        aggregate_id = str(event.aggregate.target_id)
        duplicate_index = seen_ids.get(event_id)
        if duplicate_index is not None:
            violations.append(
                _violation(
                    definition,
                    "Event history contains a duplicate event ID.",
                    (
                        _evidence(
                            path=f"/history/{index}/event_id",
                            observed=event_id,
                            expected=f"unique; first seen at index {duplicate_index}",
                            identifier=event.event_id,
                        ),
                    ),
                )
            )
        else:
            seen_ids[event_id] = index
        key_boundary = (str(event.project_id), aggregate_id, event.idempotency_key)
        prior_key_index = seen_keys.get(key_boundary)
        if prior_key_index is not None:
            violations.append(
                _violation(
                    definition,
                    "Event history contains a duplicate idempotency key.",
                    (
                        _evidence(
                            path=f"/history/{index}/idempotency_key",
                            observed=event.idempotency_key,
                            expected=f"unique; first seen at index {prior_key_index}",
                        ),
                    ),
                )
            )
        else:
            seen_keys[key_boundary] = index
        if event.project_id != context.state.metadata.project_id:
            violations.append(
                _violation(
                    definition,
                    "Event belongs to another project.",
                    (
                        _evidence(
                            path=f"/history/{index}/project_id",
                            observed=str(event.project_id),
                            expected=str(context.state.metadata.project_id),
                        ),
                    ),
                )
            )
        if event.causation_id == event.event_id:
            violations.append(
                _violation(
                    definition,
                    "Event causation self-references the event.",
                    (
                        _evidence(
                            path=f"/history/{index}/causation_id",
                            observed=event_id,
                            expected="an earlier distinct event",
                            identifier=event.event_id,
                        ),
                    ),
                )
            )
        elif (
            require_causation
            and event.causation_id is not None
            and str(event.causation_id) not in seen_ids
        ):
            violations.append(
                _violation(
                    definition,
                    "Event causation reference is missing or not earlier in history.",
                    (
                        _evidence(
                            path=f"/history/{index}/causation_id",
                            observed=str(event.causation_id),
                            expected="EventId present at an earlier history index",
                            identifier=event.causation_id,
                        ),
                    ),
                )
            )
    return tuple(violations)


def _matching_records[RecordKey](
    previous: Mapping[RecordKey, VersionedRecord],
    current: Mapping[RecordKey, VersionedRecord],
    root: str,
) -> tuple[tuple[str, VersionedRecord, VersionedRecord], ...]:
    return tuple(
        (
            f"/{root}/{key}",
            previous[key],
            current[key],
        )
        for key in sorted(set(previous).intersection(current), key=str)
    )


def _version_evidence(
    path: str,
    previous: VersionedRecord,
    current: VersionedRecord,
) -> InvariantEvidence | None:
    if current.record_version < previous.record_version:
        version_path = "/record_version" if path == "/" else f"{path}/record_version"
        return _evidence(
            path=version_path,
            observed=current.record_version,
            expected=f">= {previous.record_version}",
        )
    if (
        current.record_version == previous.record_version
        and current.contract_content_fingerprint() != previous.contract_content_fingerprint()
    ):
        return _evidence(
            path=path,
            observed=current.contract_content_fingerprint(),
            expected=previous.contract_content_fingerprint(),
            message="Content changed without incrementing record_version.",
        )
    return None


def _monotonic_record_versions(
    definition: InvariantDefinition,
    context: InvariantEvaluationContext,
) -> tuple[InvariantViolation, ...]:
    sequence = (*context.previous_snapshots, context.state)
    violations: list[InvariantViolation] = []
    for previous, current in pairwise(sequence):
        comparisons: list[tuple[str, VersionedRecord, VersionedRecord]] = [("/", previous, current)]
        comparisons.extend(
            _matching_records(
                previous.phase_execution_records,
                current.phase_execution_records,
                "phases",
            )
        )
        comparisons.extend(
            _matching_records(
                previous.artifact_registry,
                current.artifact_registry,
                "artifacts",
            )
        )
        comparisons.extend(
            _matching_records(
                previous.requirement_registry,
                current.requirement_registry,
                "requirements",
            )
        )
        comparisons.extend(
            _matching_records(
                previous.risk_registry,
                current.risk_registry,
                "risks",
            )
        )
        for path, old_record, new_record in comparisons:
            evidence = _version_evidence(path, old_record, new_record)
            if evidence is not None:
                violations.append(
                    _violation(
                        definition,
                        "Record versions are not monotonic with contractual content.",
                        (evidence,),
                    )
                )
    return tuple(violations)


_EVALUATORS: Mapping[InvariantKind, _Evaluator] = MappingProxyType(
    {
        InvariantKind.SINGLE_ACTIVE_PHASE: _single_active_phase,
        InvariantKind.LIFECYCLE_PHASE_ALIGNMENT: _lifecycle_phase_alignment,
        InvariantKind.APPROVED_BASELINE_INTEGRITY: _approved_baseline_integrity,
        InvariantKind.REQUIRED_DEPENDENCY_SATISFACTION: _required_dependency_satisfaction,
        InvariantKind.REQUIREMENT_TRACEABILITY: _requirement_traceability,
        InvariantKind.CRITICAL_RISK_CONTROL: _critical_risk_control,
        InvariantKind.TERMINAL_PHASE_CONSISTENCY: _terminal_phase_consistency,
        InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY: _immutable_history_consistency,
        InvariantKind.MONOTONIC_RECORD_VERSIONS: _monotonic_record_versions,
    }
)


def _selection_error(message: str, actual: str) -> ArchKernelError:
    return ArchKernelError(
        ErrorDetail(
            code=ErrorCode.INVARIANT_EVALUATION_ERROR,
            message=message,
            entity_type="invariant_evaluation",
            expected="known selected invariant keys",
            actual=actual,
            severity=Severity.ERROR,
        )
    )


def evaluate_invariants(
    context: InvariantEvaluationContext,
    registry: InvariantRegistry,
) -> InvariantEvaluationResult:
    """Evaluate every selected enabled invariant without mutating its inputs."""

    if context.selected_keys is not None:
        unknown = tuple(key for key in context.selected_keys if registry.get_by_key(key) is None)
        if unknown:
            raise _selection_error(
                "Invariant selection contains unknown keys.",
                ", ".join(unknown),
            )
    selected_key_set = None if context.selected_keys is None else frozenset(context.selected_keys)
    selected_scope_set = (
        None if context.selected_scopes is None else frozenset(context.selected_scopes)
    )
    evaluated: list[InvariantDefinition] = []
    skipped: list[InvariantDefinition] = []
    violations: list[InvariantViolation] = []
    for definition in registry.definitions:
        selected = (selected_key_set is None or definition.key in selected_key_set) and (
            selected_scope_set is None or definition.scope in selected_scope_set
        )
        if not definition.enabled or not selected:
            skipped.append(definition)
            continue
        evaluated.append(definition)
        try:
            violations.extend(_EVALUATORS[definition.kind](definition, context))
        except (KeyError, TypeError, ValueError) as error:
            raise ArchKernelError(
                ErrorDetail(
                    code=ErrorCode.INVARIANT_EVALUATION_ERROR,
                    message="Invariant evaluator contract failed.",
                    entity_type="invariant",
                    entity_id=str(definition.invariant_id),
                    actual=str(error),
                    severity=Severity.ERROR,
                )
            ) from error

    counts = {
        severity.value: sum(violation.severity is severity for violation in violations)
        for severity in InvariantSeverity
    }
    blocking_failure = any(violation.blocking for violation in violations)
    fingerprint_input = {
        "context": context.model_dump(mode="json"),
        "definitions": [definition.model_dump(mode="json") for definition in evaluated],
    }
    return InvariantEvaluationResult(
        success=not blocking_failure,
        blocking_failure=blocking_failure,
        evaluated_invariant_ids=tuple(item.invariant_id for item in evaluated),
        skipped_invariant_ids=tuple(item.invariant_id for item in skipped),
        violations=tuple(violations),
        counts_by_severity=freeze_json_object(counts),
        evaluated_at=context.evaluated_at,
        input_fingerprint=compute_fingerprint(fingerprint_input),
        errors=(),
    )


__all__ = ("evaluate_invariants",)
