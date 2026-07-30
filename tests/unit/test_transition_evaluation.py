"""Tests for guards, effects, and K05-integrated transition evaluation."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import (
    ArtifactId,
    EffectType,
    EffectValueSource,
    ExecutionStatus,
    GuardType,
    PatchOperationType,
    TransitionDomain,
    TransitionEffect,
    TransitionEvaluationResult,
    TransitionGuard,
    TransitionId,
    TransitionTarget,
    TypedReference,
)
from arch_kernel.kernel import ErrorCode, evaluate_transition
from arch_kernel.kernel.fingerprints import canonicalize_json
from tests.transition_helpers import (
    EVALUATED_AT,
    artifact_review_state,
    effect,
    field_guard,
    load_state,
    phase_review_state,
    registry,
    request,
)


@pytest.mark.parametrize(
    ("guard", "passes"),
    [
        (
            field_guard(
                GuardType.FIELD_EQUALS,
                "/profile/project_type",
                expected="platform",
            ),
            True,
        ),
        (
            field_guard(
                GuardType.FIELD_NOT_EQUALS,
                "/profile/project_type",
                expected="service",
            ),
            True,
        ),
        (
            field_guard(
                GuardType.FIELD_IN,
                "/profile/project_type",
                allowed_values=("platform", "service"),
            ),
            True,
        ),
        (field_guard(GuardType.FIELD_EXISTS, "/profile/project_type"), True),
        (field_guard(GuardType.FIELD_ABSENT, "/profile/missing"), True),
        (
            field_guard(
                GuardType.FIELD_EQUALS,
                "/profile/missing",
                expected=None,
            ),
            False,
        ),
        (
            field_guard(
                GuardType.FIELD_IN,
                "/profile/missing",
                allowed_values=(None,),
            ),
            False,
        ),
    ],
)
def test_field_guard_semantics(guard: TransitionGuard, passes: bool) -> None:
    state = artifact_review_state()
    definition = effect(guards=(guard,))

    result = evaluate_transition(
        state,
        request(state, definition),
        registry(definition),
        evaluated_at=EVALUATED_AT,
    )

    assert result.guard_evaluations[0].passed is passes
    assert result.allowed is passes
    if not passes:
        assert result.state_patch is None
        assert result.errors[0].code is ErrorCode.TRANSITION_GUARD_FAILED


def test_field_equality_uses_canonical_json_for_arrays() -> None:
    state = artifact_review_state()
    guard = field_guard(
        GuardType.FIELD_EQUALS,
        "/profile/objectives",
        expected=["Deliver a deterministic project state."],
    )
    definition = effect(guards=(guard,))

    result = evaluate_transition(state, request(state, definition), registry(definition))

    assert result.allowed


def test_reference_guard_passes_and_fails_inside_current_aggregate() -> None:
    state = artifact_review_state()
    requirement_id = next(iter(state.requirement_registry))
    existing = TransitionGuard(
        guard_type=GuardType.REFERENCE_EXISTS,
        reference=TypedReference(target_type="requirement", target_id=requirement_id),
    )
    missing_id = requirement_id.from_str("REQ-01HZX7M3FQ1T2Q9V8Y6K4C2B1T")
    missing = TransitionGuard(
        guard_type=GuardType.REFERENCE_EXISTS,
        reference=TypedReference(target_type="requirement", target_id=missing_id),
    )

    for guard, passes in ((existing, True), (missing, False)):
        definition = effect(guards=(guard,))
        result = evaluate_transition(state, request(state, definition), registry(definition))
        assert result.guard_evaluations[0].passed is passes


def test_no_active_phase_except_target_guard() -> None:
    state = load_state()
    active_id = next(iter(state.phase_execution_records))
    guard = TransitionGuard(guard_type=GuardType.NO_ACTIVE_PHASE_EXCEPT_TARGET)
    definition = effect(
        domain=TransitionDomain.PHASE_STATUS,
        source="active",
        destination="completed",
        key="phase.complete",
        guards=(guard,),
    )
    active_result = evaluate_transition(
        state,
        request(state, definition, entity_id=active_id),
        registry(definition),
    )
    review_state, review_id = phase_review_state()
    review_definition = effect(
        domain=TransitionDomain.PHASE_STATUS,
        source="in_review",
        destination="completed",
        key="phase.complete",
        guards=(guard,),
    )
    blocked_result = evaluate_transition(
        review_state,
        request(review_state, review_definition, entity_id=review_id),
        registry(review_definition),
    )

    assert active_result.guard_evaluations[0].passed
    assert not blocked_result.guard_evaluations[0].passed


def test_dependency_guard_uses_required_outgoing_aggregate_dependencies() -> None:
    state = artifact_review_state()
    guard = TransitionGuard(guard_type=GuardType.ALL_DEPENDENCIES_SATISFIED)
    definition = effect(guards=(guard,))
    passing = evaluate_transition(state, request(state, definition), registry(definition))

    document = state.model_dump(mode="json")
    requirement = next(iter(document["requirement_registry"].values()))
    requirement["status"] = "proposed"
    unsatisfied_state = type(state).model_validate_json(canonicalize_json(document))
    failing = evaluate_transition(
        unsatisfied_state,
        request(unsatisfied_state, definition),
        registry(definition),
    )

    assert passing.allowed
    assert not failing.allowed
    assert not failing.guard_evaluations[0].passed


def test_all_guard_failures_are_collected_in_declaration_order() -> None:
    state = artifact_review_state()
    guards = (
        field_guard(GuardType.FIELD_EQUALS, "/profile/project_type", expected="wrong"),
        field_guard(GuardType.FIELD_EXISTS, "/profile/missing"),
    )
    definition = effect(guards=guards)
    result = evaluate_transition(state, request(state, definition), registry(definition))

    assert not result.allowed
    assert tuple(item.guard for item in result.guard_evaluations) == guards
    assert len(result.errors) == 2
    assert result.state_patch is None


def test_effects_render_in_order_and_use_explicit_value_sources() -> None:
    state = artifact_review_state()
    artifact_id = next(iter(state.artifact_registry))
    effects = (
        TransitionEffect(
            effect_type=EffectType.ASSERT_FIELD,
            path_template="/artifacts/{entity_id}/owner",
            value_source=EffectValueSource.LITERAL,
            literal_value="platform-team",
        ),
        TransitionEffect(
            effect_type=EffectType.SET_FIELD,
            path_template="/artifacts/{entity_id}/status",
            value_source=EffectValueSource.TO_STATE,
        ),
    )
    definition = effect(effects=effects)
    result = evaluate_transition(
        state,
        request(state, definition),
        registry(definition),
        evaluated_at=EVALUATED_AT,
    )

    assert result.allowed
    assert result.state_patch is not None
    assert tuple(item.op for item in result.state_patch.operations) == (
        PatchOperationType.TEST,
        PatchOperationType.REPLACE,
    )
    assert str(result.state_patch.operations[0].path) == f"/artifacts/{artifact_id}/owner"
    assert result.state_patch.operations[1].value == "approved"


def test_entity_id_value_source_can_assert_the_target_identity() -> None:
    state = artifact_review_state()
    effects = (
        TransitionEffect(
            effect_type=EffectType.ASSERT_FIELD,
            path_template="/artifacts/{entity_id}/artifact_id",
            value_source=EffectValueSource.ENTITY_ID,
        ),
        effect().effects[0],
    )
    definition = effect(effects=effects)

    result = evaluate_transition(state, request(state, definition), registry(definition))

    assert result.allowed
    assert result.state_patch is not None
    assert result.state_patch.operations[0].value == str(next(iter(state.artifact_registry)))


def test_successful_artifact_transition_is_pure_and_versions_once() -> None:
    state = artifact_review_state()
    before = state.canonical_json()
    artifact_id = next(iter(state.artifact_registry))
    definition = effect()
    transition_request = request(
        state,
        definition,
        expected_from_state="under_review",
        base_state_record_version=state.record_version,
        expected_state_content_fingerprint=state.contract_content_fingerprint(),
        expected_target_record_version=state.artifact_registry[artifact_id].record_version,
        expected_target_content_fingerprint=state.artifact_registry[
            artifact_id
        ].contract_content_fingerprint(),
    )

    result = evaluate_transition(
        state,
        transition_request,
        registry(definition),
        evaluated_at=EVALUATED_AT,
    )

    assert result.allowed
    assert result.dry_run_result is not None
    assert result.dry_run_result.status is ExecutionStatus.COMPLETED
    projected = result.dry_run_result.projected_state
    assert projected is not None
    assert projected.record_version == state.record_version + 1
    assert (
        projected.artifact_registry[artifact_id].record_version
        == state.artifact_registry[artifact_id].record_version + 1
    )
    assert projected.artifact_registry[artifact_id].updated_at == EVALUATED_AT
    assert state.canonical_json() == before


def test_successful_phase_transition_uses_closed_resolver() -> None:
    state, phase_id = phase_review_state()
    definition = effect(
        domain=TransitionDomain.PHASE_STATUS,
        source="in_review",
        destination="completed",
        key="phase.complete",
    )
    result = evaluate_transition(
        state,
        request(state, definition, entity_id=phase_id),
        registry(definition),
        evaluated_at=EVALUATED_AT,
    )

    assert result.allowed
    assert result.current_state == "in_review"
    assert result.dry_run_result is not None
    assert result.dry_run_result.projected_state is not None
    assert (
        result.dry_run_result.projected_state.phase_execution_records[phase_id].status.value
        == "completed"
    )


def test_phase_effect_can_source_the_explicit_evaluation_time() -> None:
    state, phase_id = phase_review_state()
    effects = (
        TransitionEffect(
            effect_type=EffectType.SET_FIELD,
            path_template="/phases/{entity_id}/completed_at",
            value_source=EffectValueSource.EVALUATED_AT,
        ),
        TransitionEffect(
            effect_type=EffectType.SET_FIELD,
            path_template="/phases/{entity_id}/status",
            value_source=EffectValueSource.TO_STATE,
        ),
    )
    definition = effect(
        domain=TransitionDomain.PHASE_STATUS,
        source="in_review",
        destination="completed",
        key="phase.complete",
        effects=effects,
    )

    result = evaluate_transition(
        state,
        request(state, definition, entity_id=phase_id),
        registry(definition),
        evaluated_at=EVALUATED_AT,
    )

    assert result.allowed
    assert result.dry_run_result is not None
    assert result.dry_run_result.projected_state is not None
    assert (
        result.dry_run_result.projected_state.phase_execution_records[phase_id].completed_at
        == EVALUATED_AT
    )


@pytest.mark.parametrize(
    ("domain", "source", "destination", "registry_name", "transition_key"),
    [
        (
            TransitionDomain.RISK_STATUS,
            "open",
            "accepted",
            "risk_registry",
            "risk.accept",
        ),
        (
            TransitionDomain.REQUIREMENT_STATUS,
            "accepted",
            "verified",
            "requirement_registry",
            "requirement.verify",
        ),
    ],
)
def test_additional_contract_backed_domains_are_executable(
    domain: TransitionDomain,
    source: str,
    destination: str,
    registry_name: str,
    transition_key: str,
) -> None:
    state = load_state()
    target_registry = getattr(state, registry_name)
    target_id = next(iter(target_registry))
    definition = effect(
        domain=domain,
        source=source,
        destination=destination,
        key=transition_key,
    )

    result = evaluate_transition(
        state,
        request(state, definition, entity_id=target_id),
        registry(definition),
        evaluated_at=EVALUATED_AT,
    )

    assert result.allowed
    assert result.dry_run_result is not None
    assert result.dry_run_result.projected_state is not None
    projected_registry = getattr(result.dry_run_result.projected_state, registry_name)
    assert projected_registry[target_id].status == destination


def test_project_lifecycle_self_transition_is_an_unambiguous_no_op() -> None:
    state = load_state()
    definition = effect(
        domain=TransitionDomain.PROJECT_LIFECYCLE,
        source="active",
        destination="active",
        key="project.reaffirm",
        allow_self_transition=True,
    )

    result = evaluate_transition(
        state,
        request(state, definition, entity_id=state.metadata.project_id),
        registry(definition),
        evaluated_at=EVALUATED_AT,
    )

    assert result.allowed
    assert result.dry_run_result is not None
    assert result.dry_run_result.changed_paths == ()
    assert result.dry_run_result.projected_state is not None
    assert result.dry_run_result.projected_state.record_version == state.record_version


def test_resolution_and_source_failures_are_structured() -> None:
    state = artifact_review_state()
    definition = effect()
    unknown = definition.model_copy(
        update={"transition_id": TransitionId.from_str("TRN-01HZX7M3FQ1T2Q9V8Y6K4C2B1V")}
    )
    missing_request = request(
        state,
        unknown,
        transition_key=None,
        transition_id=unknown.transition_id,
    )
    missing = evaluate_transition(state, missing_request, registry(definition))
    wrong_source_state = load_state()
    wrong_source = evaluate_transition(
        wrong_source_state,
        request(wrong_source_state, definition),
        registry(definition),
    )
    stale_source = evaluate_transition(
        state,
        request(state, definition, expected_from_state="draft"),
        registry(definition),
    )

    assert missing.errors[0].code is ErrorCode.TRANSITION_NOT_FOUND
    assert wrong_source.errors[0].code is ErrorCode.INVALID_TRANSITION_DEFINITION
    assert stale_source.errors[0].code is ErrorCode.STALE_OBJECT_VERSION


def test_project_target_and_transition_domain_identity_failures_are_structured() -> None:
    state = artifact_review_state()
    definition = effect()
    wrong_project = request(
        state,
        definition,
        project_id=state.metadata.project_id.from_str("PRJ-01HZX7M3FQ1T2Q9V8Y6K4C2B1Z"),
    )
    missing_target = request(
        state,
        definition,
        entity_id=ArtifactId.from_str("ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1Z"),
    )
    phase_definition = effect(
        domain=TransitionDomain.PHASE_STATUS,
        source="active",
        destination="completed",
        key="phase.complete",
    )
    mismatched_domain = request(state, definition).model_copy(
        update={
            "transition_key": phase_definition.transition_key,
            "target": TransitionTarget(
                domain=TransitionDomain.ARTIFACT_STATUS,
                entity_id=next(iter(state.artifact_registry)),
            ),
        }
    )

    assert (
        evaluate_transition(state, wrong_project, registry(definition)).errors[0].code
        is ErrorCode.INVALID_REFERENCE
    )
    assert (
        evaluate_transition(state, missing_target, registry(definition)).errors[0].code
        is ErrorCode.INVALID_REFERENCE
    )
    assert (
        evaluate_transition(state, mismatched_domain, registry(phase_definition)).errors[0].code
        is ErrorCode.INVALID_REFERENCE
    )


def test_stale_root_and_target_preconditions_fail_through_k05() -> None:
    state = artifact_review_state()
    definition = effect()
    stale_root = evaluate_transition(
        state,
        request(state, definition, base_state_record_version=state.record_version + 1),
        registry(definition),
    )
    stale_target = evaluate_transition(
        state,
        request(state, definition, expected_target_record_version=99),
        registry(definition),
    )

    assert stale_root.dry_run_result is not None
    assert stale_root.errors[0].code is ErrorCode.STALE_STATE_VERSION
    assert stale_target.dry_run_result is not None
    assert stale_target.errors[0].code is ErrorCode.STALE_OBJECT_VERSION


def test_stale_fingerprint_preconditions_fail_deterministically() -> None:
    state = artifact_review_state()
    definition = effect()
    stale = "sha256:" + ("0" * 64)
    stale_root = evaluate_transition(
        state,
        request(state, definition, expected_state_content_fingerprint=stale),
        registry(definition),
    )
    stale_target = evaluate_transition(
        state,
        request(state, definition, expected_target_content_fingerprint=stale),
        registry(definition),
    )

    assert stale_root.errors[0].code is ErrorCode.STALE_STATE_VERSION
    assert stale_target.errors[0].code is ErrorCode.STALE_OBJECT_VERSION


def test_failed_assert_effect_denies_with_dry_run_and_no_projection() -> None:
    state = artifact_review_state()
    definition = effect(
        effects=(
            TransitionEffect(
                effect_type=EffectType.ASSERT_FIELD,
                path_template="/artifacts/{entity_id}/owner",
                value_source=EffectValueSource.LITERAL,
                literal_value="wrong",
            ),
            effect().effects[0],
        )
    )
    result = evaluate_transition(state, request(state, definition), registry(definition))

    assert not result.allowed
    assert result.state_patch is not None
    assert result.dry_run_result is not None
    assert result.dry_run_result.projected_state is None
    assert result.errors[0].code is ErrorCode.PATCH_TEST_FAILED


def test_fixed_inputs_and_time_produce_identical_serialized_results() -> None:
    state = artifact_review_state()
    definition = effect()
    transition_request = request(state, definition)
    transition_registry = registry(definition)

    first = evaluate_transition(
        state,
        transition_request,
        transition_registry,
        evaluated_at=EVALUATED_AT + timedelta(minutes=1),
    )
    second = evaluate_transition(
        state,
        transition_request,
        transition_registry,
        evaluated_at=EVALUATED_AT + timedelta(minutes=1),
    )

    assert first.model_dump_json() == second.model_dump_json()
    assert TransitionEvaluationResult.model_validate_json(first.model_dump_json()) == first
    with pytest.raises(ValidationError):
        first.allowed = False
