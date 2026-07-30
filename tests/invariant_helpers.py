"""Deterministic builders for WP-K07 invariant tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from arch_kernel.contracts import (
    EventEnvelope,
    EventId,
    InvariantDefinition,
    InvariantEvaluationContext,
    InvariantId,
    InvariantKind,
    InvariantScope,
    InvariantSeverity,
    PhaseId,
    ProjectState,
    SemanticVersion,
)
from arch_kernel.kernel import InvariantRegistry

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures"
EVALUATED_AT = datetime(2026, 7, 25, 19, 0, tzinfo=UTC)
VERSION = SemanticVersion.parse("1.0.0")

_KINDS = tuple(InvariantKind)
_SCOPES = {
    InvariantKind.SINGLE_ACTIVE_PHASE: InvariantScope.PROJECT,
    InvariantKind.LIFECYCLE_PHASE_ALIGNMENT: InvariantScope.LIFECYCLE,
    InvariantKind.APPROVED_BASELINE_INTEGRITY: InvariantScope.ARTIFACT,
    InvariantKind.REQUIRED_DEPENDENCY_SATISFACTION: InvariantScope.DEPENDENCY,
    InvariantKind.REQUIREMENT_TRACEABILITY: InvariantScope.REQUIREMENT,
    InvariantKind.CRITICAL_RISK_CONTROL: InvariantScope.RISK,
    InvariantKind.TERMINAL_PHASE_CONSISTENCY: InvariantScope.PHASE,
    InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY: InvariantScope.HISTORY,
    InvariantKind.MONOTONIC_RECORD_VERSIONS: InvariantScope.HISTORY,
}
_KEYS = {
    InvariantKind.SINGLE_ACTIVE_PHASE: "project.phase.single_active",
    InvariantKind.LIFECYCLE_PHASE_ALIGNMENT: "project.lifecycle.phase_alignment",
    InvariantKind.APPROVED_BASELINE_INTEGRITY: "project.baseline.approved_integrity",
    InvariantKind.REQUIRED_DEPENDENCY_SATISFACTION: "project.dependency.required_satisfaction",
    InvariantKind.REQUIREMENT_TRACEABILITY: "project.requirement.traceability",
    InvariantKind.CRITICAL_RISK_CONTROL: "project.risk.critical_control",
    InvariantKind.TERMINAL_PHASE_CONSISTENCY: "project.phase.terminal_consistency",
    InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY: "project.history.immutable_consistency",
    InvariantKind.MONOTONIC_RECORD_VERSIONS: "project.history.monotonic_versions",
}
_ID_SUFFIXES = ("M", "N", "P", "Q", "R", "S", "T", "V", "W")


def load_state() -> ProjectState:
    return ProjectState.model_validate_json(
        (FIXTURE_ROOT / "valid" / "minimal_project_state.json").read_text(encoding="utf-8")
    )


def load_event() -> EventEnvelope:
    return EventEnvelope.model_validate_json(
        (FIXTURE_ROOT / "valid" / "event_envelope.json").read_text(encoding="utf-8")
    )


def definition(
    kind: InvariantKind,
    *,
    configuration: object | None = None,
    severity: InvariantSeverity = InvariantSeverity.ERROR,
    blocking: bool = True,
    enabled: bool = True,
    priority: int | None = None,
    invariant_id: InvariantId | None = None,
    key: str | None = None,
    scope: InvariantScope | None = None,
) -> InvariantDefinition:
    index = _KINDS.index(kind)
    return InvariantDefinition.model_validate(
        {
            "invariant_id": invariant_id
            or InvariantId.from_str(f"INV-01HZX7M3FQ1T2Q9V8Y6K4C2B1{_ID_SUFFIXES[index]}"),
            "key": key or _KEYS[kind],
            "title": kind.value.replace("_", " ").title(),
            "description": f"Canonical invariant for {kind.value}.",
            "kind": kind,
            "scope": scope or _SCOPES[kind],
            "severity": severity,
            "enabled": enabled,
            "blocking": blocking,
            "priority": index * 10 if priority is None else priority,
            "configuration": {} if configuration is None else configuration,
            "remediation_hint": "Correct the reported aggregate evidence.",
            "contract_version": VERSION,
            "schema_uri": f"urn:arch:invariants:{kind.value}:1.0.0",
        }
    )


def canonical_definitions() -> tuple[InvariantDefinition, ...]:
    return tuple(definition(kind) for kind in InvariantKind)


def canonical_registry() -> InvariantRegistry:
    return InvariantRegistry(canonical_definitions())


def context(
    state: ProjectState | None = None,
    *,
    history: tuple[EventEnvelope, ...] = (),
    previous_snapshots: tuple[ProjectState, ...] = (),
    **changes: object,
) -> InvariantEvaluationContext:
    return InvariantEvaluationContext.model_validate(
        {
            "state": state or load_state(),
            "evaluated_at": EVALUATED_AT,
            "history": history,
            "previous_snapshots": previous_snapshots,
            **changes,
        }
    )


def valid_history() -> tuple[EventEnvelope, ...]:
    first = load_event()
    second_id = EventId.from_str("EVT-01HZX7M3FQ1T2Q9V8Y6K4C2B1H")
    second = first.model_copy(
        update={
            "event_id": second_id,
            "event_type": "project.phase.completed",
            "occurred_at": first.occurred_at + timedelta(minutes=1),
            "recorded_at": first.recorded_at + timedelta(minutes=1),
            "correlation_id": first.event_id,
            "causation_id": first.event_id,
            "idempotency_key": "project/phase/completion:001",
        },
        deep=True,
    )
    return (first, second)


def state_with_second_phase(
    *,
    status: str,
    completed_at: datetime | None = None,
    blocked_reason: str | None = None,
) -> tuple[ProjectState, PhaseId]:
    state = load_state()
    source = next(iter(state.phase_execution_records.values()))
    phase_id = PhaseId.from_str("PHS-01HZX7M3FQ1T2Q9V8Y6K4C2B1P")
    phase = source.model_copy(
        update={
            "phase_id": phase_id,
            "phase_code": type(source.phase_code).F03,
            "status": type(source.status)(status),
            "completed_at": completed_at,
            "blocked_reason": blocked_reason,
            "artifact_ids": (),
            "requirement_ids": (),
        },
        deep=True,
    )
    records = {**state.phase_execution_records, phase_id: phase}
    return state.model_copy(update={"phase_execution_records": records}, deep=True), phase_id
