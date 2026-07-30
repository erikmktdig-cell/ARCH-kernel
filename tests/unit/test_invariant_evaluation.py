"""Exhaustive pass/fail tests for the nine canonical invariants."""

from __future__ import annotations

from datetime import timedelta

import pytest

from arch_kernel.contracts import (
    ArtifactId,
    EventId,
    InvariantEvaluationResult,
    InvariantKind,
    InvariantScope,
    InvariantSeverity,
    PhaseStatus,
    ProjectId,
)
from arch_kernel.kernel import (
    ArchKernelError,
    ErrorCode,
    InvariantRegistry,
    evaluate_invariants,
)
from tests.invariant_helpers import (
    EVALUATED_AT,
    canonical_registry,
    context,
    definition,
    load_event,
    load_state,
    state_with_second_phase,
    valid_history,
)


def _evaluate(kind: InvariantKind, invariant_context: object) -> InvariantEvaluationResult:
    selected = definition(kind)
    return evaluate_invariants(
        invariant_context,  # type: ignore[arg-type]
        InvariantRegistry((selected,)),
    )


def test_canonical_registry_passes_minimal_current_state() -> None:
    result = evaluate_invariants(context(), canonical_registry())

    assert result.success
    assert not result.blocking_failure
    assert result.violations == ()
    assert len(result.evaluated_invariant_ids) == 9
    assert result.counts_by_severity == {
        "info": 0,
        "warning": 0,
        "error": 0,
        "critical": 0,
    }


def test_single_active_phase_reports_stable_independent_diagnostics() -> None:
    state, phase_id = state_with_second_phase(status="active")
    result = _evaluate(InvariantKind.SINGLE_ACTIVE_PHASE, context(state))

    assert not result.success
    assert result.violations[0].kind is InvariantKind.SINGLE_ACTIVE_PHASE
    assert tuple(item.path for item in result.violations[0].evidence) == tuple(
        sorted(
            (
                f"/phases/{next(iter(load_state().phase_execution_records))}/status",
                f"/phases/{phase_id}/status",
            )
        )
    )


def test_lifecycle_phase_alignment_reports_status_and_missing_phase() -> None:
    state = load_state()
    lifecycle = state.lifecycle.model_copy(
        update={"status": PhaseStatus.READY},
        deep=True,
    )
    misaligned = state.model_copy(update={"lifecycle": lifecycle}, deep=True)
    first = _evaluate(
        InvariantKind.LIFECYCLE_PHASE_ALIGNMENT,
        context(misaligned),
    )

    missing_id = next(iter(state.phase_execution_records)).from_str(
        "PHS-01HZX7M3FQ1T2Q9V8Y6K4C2B1Z"
    )
    missing_lifecycle = state.lifecycle.model_copy(
        update={"current_phase_id": missing_id},
        deep=True,
    )
    missing = state.model_copy(update={"lifecycle": missing_lifecycle}, deep=True)
    second = _evaluate(
        InvariantKind.LIFECYCLE_PHASE_ALIGNMENT,
        context(missing),
    )

    assert first.violations[0].evidence[0].observed == "active"
    assert second.violations[0].evidence[0].observed == str(missing_id)


def test_approved_baseline_integrity_checks_resolution_status_and_fingerprint() -> None:
    state = load_state()
    missing_id = ArtifactId.from_str("ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1Z")
    missing = state.model_copy(
        update={"active_baseline_artifact_ids": (missing_id,)},
        deep=True,
    )
    missing_result = _evaluate(
        InvariantKind.APPROVED_BASELINE_INTEGRITY,
        context(missing),
    )

    artifact_id = next(iter(state.artifact_registry))
    artifact = state.artifact_registry[artifact_id].model_copy(
        update={"status": type(state.artifact_registry[artifact_id].status).DRAFT},
        deep=True,
    )
    invalid = state.model_copy(
        update={"artifact_registry": {artifact_id: artifact}},
        deep=True,
    )
    configured = definition(
        InvariantKind.APPROVED_BASELINE_INTEGRITY,
        configuration={"require_content_fingerprint": True},
    )
    invalid_result = evaluate_invariants(
        context(invalid),
        InvariantRegistry((configured,)),
    )

    assert missing_result.violations
    assert invalid_result.violations[0].evidence[0].observed == "draft"


def test_baseline_configuration_can_require_a_content_fingerprint() -> None:
    state = load_state()
    artifact_id = next(iter(state.artifact_registry))
    artifact = state.artifact_registry[artifact_id].model_copy(
        update={"content_fingerprint": None},
        deep=True,
    )
    state = state.model_copy(
        update={"artifact_registry": {artifact_id: artifact}},
        deep=True,
    )
    invariant = definition(
        InvariantKind.APPROVED_BASELINE_INTEGRITY,
        configuration={"require_content_fingerprint": True},
    )

    result = evaluate_invariants(context(state), InvariantRegistry((invariant,)))

    assert result.violations[0].evidence[0].path == f"/artifacts/{artifact_id}/content_fingerprint"


def test_required_dependency_satisfaction_reports_unsatisfied_target() -> None:
    state = load_state()
    requirement_id = next(iter(state.requirement_registry))
    requirement = state.requirement_registry[requirement_id].model_copy(
        update={"status": "proposed"},
        deep=True,
    )
    invalid = state.model_copy(
        update={"requirement_registry": {requirement_id: requirement}},
        deep=True,
    )

    result = _evaluate(
        InvariantKind.REQUIRED_DEPENDENCY_SATISFACTION,
        context(invalid),
    )

    assert len(result.violations) == 1
    assert result.violations[0].evidence[1].observed == "proposed"


def test_requirement_traceability_reports_untraced_selected_status() -> None:
    state = load_state()
    requirement_id = next(iter(state.requirement_registry))
    requirement = state.requirement_registry[requirement_id].model_copy(
        update={"artifact_ids": ()},
        deep=True,
    )
    invalid = state.model_copy(
        update={
            "requirement_registry": {requirement_id: requirement},
            "dependency_graph": (),
        },
        deep=True,
    )

    result = _evaluate(InvariantKind.REQUIREMENT_TRACEABILITY, context(invalid))

    assert result.violations[0].evidence[0].observed == ()


def test_critical_risk_control_uses_existing_score_mitigation_and_status() -> None:
    state = load_state()
    risk_id = next(iter(state.risk_registry))
    uncontrolled = state.risk_registry[risk_id].model_copy(
        update={"probability": 5, "impact": 5, "status": "open", "mitigation": None},
        deep=True,
    )
    invalid = state.model_copy(
        update={"risk_registry": {risk_id: uncontrolled}},
        deep=True,
    )
    result = _evaluate(InvariantKind.CRITICAL_RISK_CONTROL, context(invalid))

    controlled = uncontrolled.model_copy(update={"mitigation": "Reduce exposure."})
    valid = state.model_copy(
        update={"risk_registry": {risk_id: controlled}},
        deep=True,
    )
    passing = _evaluate(InvariantKind.CRITICAL_RISK_CONTROL, context(valid))

    assert result.violations[0].evidence[0].observed == 25
    assert passing.violations == ()


def test_terminal_phase_consistency_reports_timestamp_and_outputs() -> None:
    state, phase_id = state_with_second_phase(status="completed")
    invariant = definition(
        InvariantKind.TERMINAL_PHASE_CONSISTENCY,
        configuration={"require_completed_at": True, "require_outputs": True},
    )

    result = evaluate_invariants(context(state), InvariantRegistry((invariant,)))

    assert tuple(item.path for item in result.violations[0].evidence) == (
        f"/phases/{phase_id}/completed_at",
        f"/phases/{phase_id}/artifact_ids",
    )


def test_history_is_normalized_and_valid_causality_passes() -> None:
    first, second = valid_history()
    invariant_context = context(history=(second, first))

    result = _evaluate(
        InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY,
        invariant_context,
    )

    assert result.violations == ()
    assert invariant_context.history == (first, second)


def test_history_reports_duplicate_id_and_idempotency_key() -> None:
    first = load_event()
    duplicate_id = first.model_copy(
        update={"idempotency_key": "project/phase/other:001"},
        deep=True,
    )
    id_result = _evaluate(
        InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY,
        context(history=(first, duplicate_id)),
    )

    duplicate_key = first.model_copy(
        update={
            "event_id": EventId.from_str("EVT-01HZX7M3FQ1T2Q9V8Y6K4C2B1H"),
            "occurred_at": first.occurred_at + timedelta(seconds=1),
            "recorded_at": first.recorded_at + timedelta(seconds=1),
        },
        deep=True,
    )
    key_result = _evaluate(
        InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY,
        context(history=(first, duplicate_key)),
    )

    assert "duplicate event ID" in id_result.violations[0].message
    assert "duplicate idempotency key" in key_result.violations[0].message


def test_history_reports_forward_causation_self_reference_and_other_project() -> None:
    first, second = valid_history()
    forward = first.model_copy(
        update={
            "correlation_id": second.event_id,
            "causation_id": second.event_id,
        },
        deep=True,
    )
    forward_result = _evaluate(
        InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY,
        context(history=(forward, second)),
    )

    self_caused = first.model_copy(
        update={"correlation_id": first.event_id, "causation_id": first.event_id},
        deep=True,
    )
    other_project = second.model_copy(
        update={"project_id": ProjectId.from_str("PRJ-01HZX7M3FQ1T2Q9V8Y6K4C2B1Z")},
        deep=True,
    )
    combined = _evaluate(
        InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY,
        context(history=(self_caused, other_project)),
    )

    assert "missing or not earlier" in forward_result.violations[0].message
    assert {item.message for item in combined.violations} >= {
        "Event causation self-references the event.",
        "Event belongs to another project.",
    }


def test_monotonic_versions_pass_increase_and_report_decrease() -> None:
    current = load_state()
    previous = current.model_copy(
        update={"record_version": 1, "state_version_updated": 0},
        deep=True,
    )
    increased = current.model_copy(
        update={"record_version": 2, "state_version_updated": 2},
        deep=True,
    )
    passing = _evaluate(
        InvariantKind.MONOTONIC_RECORD_VERSIONS,
        context(increased, previous_snapshots=(previous,)),
    )

    newer_previous = current.model_copy(
        update={"record_version": 2},
        deep=True,
    )
    failing = _evaluate(
        InvariantKind.MONOTONIC_RECORD_VERSIONS,
        context(current, previous_snapshots=(newer_previous,)),
    )

    assert passing.violations == ()
    assert failing.violations[0].evidence[0].path == "/record_version"


def test_unchanged_version_with_changed_content_is_a_violation() -> None:
    previous = load_state()
    profile = previous.profile.model_copy(update={"project_type": "service"}, deep=True)
    current = previous.model_copy(update={"profile": profile}, deep=True)

    result = _evaluate(
        InvariantKind.MONOTONIC_RECORD_VERSIONS,
        context(current, previous_snapshots=(previous,)),
    )

    assert (
        result.violations[0].evidence[0].message
        == "Content changed without incrementing record_version."
    )


def test_selection_disabled_rules_and_unknown_keys_are_fail_closed() -> None:
    enabled = definition(InvariantKind.SINGLE_ACTIVE_PHASE)
    disabled = definition(
        InvariantKind.CRITICAL_RISK_CONTROL,
        enabled=False,
    )
    registry = InvariantRegistry((disabled, enabled))
    selected = evaluate_invariants(
        context(selected_scopes=(InvariantScope.PROJECT,)),
        registry,
    )

    assert selected.evaluated_invariant_ids == (enabled.invariant_id,)
    assert disabled.invariant_id in selected.skipped_invariant_ids
    with pytest.raises(ArchKernelError) as raised:
        evaluate_invariants(
            context(selected_keys=("unknown.invariant.key",)),
            registry,
        )
    assert raised.value.detail.code is ErrorCode.INVARIANT_EVALUATION_ERROR


def test_nonblocking_warning_does_not_fail_but_blocking_violation_does() -> None:
    state, _ = state_with_second_phase(status="active")
    warning = definition(
        InvariantKind.SINGLE_ACTIVE_PHASE,
        severity=InvariantSeverity.WARNING,
        blocking=False,
    )
    warning_result = evaluate_invariants(
        context(state),
        InvariantRegistry((warning,)),
    )
    blocking = warning.model_copy(update={"blocking": True})
    blocking_result = evaluate_invariants(
        context(state),
        InvariantRegistry((blocking,)),
    )

    assert warning_result.success
    assert not warning_result.blocking_failure
    assert not blocking_result.success
    assert blocking_result.blocking_failure


def test_evaluation_accumulates_is_pure_deterministic_and_round_trips() -> None:
    state, _ = state_with_second_phase(status="active")
    risk_id = next(iter(state.risk_registry))
    risk = state.risk_registry[risk_id].model_copy(
        update={"probability": 5, "impact": 5},
        deep=True,
    )
    state = state.model_copy(
        update={"risk_registry": {risk_id: risk}},
        deep=True,
    )
    before = state.canonical_json()
    registry = InvariantRegistry(
        (
            definition(InvariantKind.SINGLE_ACTIVE_PHASE),
            definition(InvariantKind.CRITICAL_RISK_CONTROL),
        )
    )
    invariant_context = context(state)

    first = evaluate_invariants(invariant_context, registry)
    second = evaluate_invariants(invariant_context, registry)

    assert len(first.violations) == 2
    assert first.model_dump_json() == second.model_dump_json()
    assert InvariantEvaluationResult.model_validate_json(first.model_dump_json()) == first
    assert state.canonical_json() == before
    assert first.evaluated_at == EVALUATED_AT
