"""C01 contract and transition tests for generic workflow authority."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import (
    EffectType,
    EffectValueSource,
    PhaseCode,
    PhaseStatus,
    TransitionDefinition,
    TransitionDomain,
    TransitionEffect,
    WorkflowDefinition,
    WorkflowId,
    WorkflowNamespace,
    WorkflowStateKey,
    WorkflowStateRecord,
)
from arch_kernel.kernel import TransitionRegistry, WorkflowDefinitionRegistry, evaluate_transition
from arch_kernel.kernel.errors import ArchKernelError, ErrorCode
from arch_kernel.kernel.fingerprints import canonicalize_json
from arch_kernel.kernel.workflow_registry import workflow_record_matches_definition
from tests.workflow_helpers import (
    WORKFLOW_ID,
    project_with_workflow,
    workflow_definition,
    workflow_request,
    workflow_transition,
)


def test_workflow_definition_round_trips_canonically_and_deeply_frozen() -> None:
    definition = workflow_definition(states=("released", "draft", "approved"))
    restored = WorkflowDefinition.model_validate_json(definition.canonical_json())

    assert tuple(map(str, definition.allowed_states)) == ("approved", "draft", "released")
    assert restored == definition
    assert restored.definition_fingerprint() == definition.definition_fingerprint()
    with pytest.raises((ValidationError, FrozenInstanceError)):
        definition.initial_state = WorkflowStateKey.parse("approved")
    with pytest.raises(AttributeError):
        definition.allowed_states.append(WorkflowStateKey.parse("blocked"))  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "value",
    ["single", "Upper.case", "space .owner", "owner..flow", "owner-flow.main"],
)
def test_workflow_namespace_rejects_noncanonical_values(value: str) -> None:
    with pytest.raises(ValueError, match="canonical grammar"):
        WorkflowNamespace.parse(value)


def test_workflow_definition_rejects_duplicate_and_unknown_initial_states() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        workflow_definition(states=())
    with pytest.raises(ValidationError, match="duplicate"):
        workflow_definition(states=("draft", "draft"))
    with pytest.raises(ValidationError, match="initial_state"):
        workflow_definition(initial_state="missing")


def test_initialization_binds_exact_definition_identity_and_fingerprint() -> None:
    state, definition = project_with_workflow()
    record = state.workflow_registry[WORKFLOW_ID]

    assert record.namespace == definition.namespace
    assert record.definition_version == definition.definition_version
    assert record.definition_fingerprint == definition.definition_fingerprint()
    assert record.current_state == definition.initial_state


def test_workflow_definition_registry_is_order_independent_and_immutable() -> None:
    first = workflow_definition(namespace="example.alpha")
    second = workflow_definition(namespace="example.beta").model_copy(
        update={"workflow_id": WorkflowId.from_str("WFL-01HZX7M3FQ1T2Q9V8Y6K4C2B1B")}
    )
    left = WorkflowDefinitionRegistry((first, second))
    right = WorkflowDefinitionRegistry((second, first))

    assert left.definitions == right.definitions
    assert left.get(first.namespace, first.definition_version) == first
    with pytest.raises(FrozenInstanceError):
        left.definitions = ()  # type: ignore[misc]


def test_workflow_definition_registry_rejects_invalid_collections_and_duplicates() -> None:
    definition = workflow_definition()
    with pytest.raises(TypeError, match="tuple"):
        WorkflowDefinitionRegistry([definition])  # type: ignore[arg-type]

    same_identity = workflow_definition().model_copy(
        update={"workflow_id": WorkflowId.from_str("WFL-01HZX7M3FQ1T2Q9V8Y6K4C2B1B")}
    )
    with pytest.raises(ValueError, match="namespace and definition version"):
        WorkflowDefinitionRegistry((definition, same_identity))

    same_id = workflow_definition(namespace="example.other")
    with pytest.raises(ValueError, match="definition ID"):
        WorkflowDefinitionRegistry((definition, same_id))


def test_workflow_record_validation_and_definition_match_fail_closed() -> None:
    state, definition = project_with_workflow()
    record = state.workflow_registry[WORKFLOW_ID]
    assert workflow_record_matches_definition(record, definition)

    mismatched = record.model_copy(update={"current_state": WorkflowStateKey.parse("unknown")})
    assert not workflow_record_matches_definition(mismatched, definition)

    payload = record.model_dump(mode="json")
    payload["definition_fingerprint"] = "invalid"
    with pytest.raises(ValidationError, match="definition_fingerprint"):
        WorkflowStateRecord.model_validate_json(canonicalize_json(payload))


def test_registry_rejects_unknown_workflow_and_state_space_bypass() -> None:
    definition = workflow_definition()
    transition = workflow_transition(definition)
    with pytest.raises(ArchKernelError) as unknown:
        TransitionRegistry((transition,))
    assert unknown.value.detail.code is ErrorCode.INVALID_TRANSITION_DEFINITION

    unbound = TransitionDefinition.model_validate_json(
        canonicalize_json(
            transition.model_dump(
                mode="json",
                exclude={
                    "workflow_namespace",
                    "workflow_definition_version",
                    "workflow_definition_fingerprint",
                },
            )
        )
    )
    with pytest.raises(ArchKernelError, match="WorkflowTransitionDefinition"):
        TransitionRegistry((unbound,), (definition,))

    invalid = workflow_transition(definition, destination="not_declared")
    with pytest.raises(ArchKernelError, match="invalid destination"):
        TransitionRegistry((invalid,), (definition,))

    stale_definition = transition.model_copy(
        update={"workflow_definition_fingerprint": "sha256:" + ("0" * 64)}
    )
    with pytest.raises(ArchKernelError, match="fingerprint does not match"):
        TransitionRegistry((stale_definition,), (definition,))


def test_registry_rejects_cross_workflow_effect_surface() -> None:
    definition = workflow_definition()
    unsafe = workflow_transition(
        definition,
        effects=(
            TransitionEffect(
                effect_type=EffectType.SET_FIELD,
                path_template="/lifecycle/status",
                value_source=EffectValueSource.TO_STATE,
            ),
        ),
    )

    with pytest.raises(ArchKernelError, match="outside its domain"):
        TransitionRegistry((unsafe,), (definition,))


def test_workflow_transition_is_pure_scoped_and_versions_exact_record_once() -> None:
    state, definition = project_with_workflow()
    transition = workflow_transition(definition)
    registry = TransitionRegistry((transition,), (definition,))
    before = state.canonical_json()

    result = evaluate_transition(state, workflow_request(state, transition), registry)

    assert result.allowed
    assert state.canonical_json() == before
    assert result.state_patch is not None
    assert tuple(map(str, result.state_patch.scope)) == (f"/workflows/{WORKFLOW_ID}",)
    assert result.dry_run_result is not None
    projected = result.dry_run_result.projected_state
    assert projected is not None
    changed = projected.workflow_registry[WORKFLOW_ID]
    assert str(changed.current_state) == "approved"
    assert changed.record_version == 2
    assert changed.state_version_updated == state.record_version + 1
    assert projected.record_version == state.record_version + 1
    assert projected.lifecycle == state.lifecycle
    assert projected.phase_execution_records == state.phase_execution_records


def test_workflow_transition_fails_closed_for_missing_or_mismatched_authority() -> None:
    state, definition = project_with_workflow()
    transition = workflow_transition(definition)
    registry = TransitionRegistry((transition,), (definition,))
    missing_preconditions = workflow_request(state, transition).model_copy(
        update={
            "expected_target_record_version": None,
            "expected_target_content_fingerprint": None,
        }
    )
    missing = evaluate_transition(state, missing_preconditions, registry)

    document = state.model_dump(mode="json")
    document["workflow_registry"][str(WORKFLOW_ID)]["namespace"] = "other.workflow"
    mismatched_state = type(state).model_validate_json(canonicalize_json(document))
    mismatch = evaluate_transition(
        mismatched_state,
        workflow_request(mismatched_state, transition),
        registry,
    )

    assert not missing.allowed
    assert missing.errors[0].code is ErrorCode.STALE_OBJECT_VERSION
    assert not mismatch.allowed
    assert mismatch.errors[0].code is ErrorCode.INVALID_REFERENCE

    empty_document = state.model_dump(mode="json")
    empty_document["workflow_registry"] = {}
    empty_state = type(state).model_validate_json(canonicalize_json(empty_document))
    missing_target = evaluate_transition(
        empty_state,
        workflow_request(state, transition),
        registry,
    )
    assert not missing_target.allowed
    assert missing_target.errors[0].code is ErrorCode.INVALID_REFERENCE


def test_workflow_transition_indexes_are_namespace_and_order_independent() -> None:
    first_definition = workflow_definition(namespace="example.alpha")
    second_definition = workflow_definition(namespace="example.beta").model_copy(
        update={"workflow_id": WorkflowId.from_str("WFL-01HZX7M3FQ1T2Q9V8Y6K4C2B1B")}
    )
    first = workflow_transition(first_definition, key="workflow.alpha")
    second = workflow_transition(
        second_definition,
        transition_id="TRN-01HZX7M3FQ1T2Q9V8Y6K4C2B1B",
        key="workflow.beta",
    )
    left = TransitionRegistry((first, second), (first_definition, second_definition))
    right = TransitionRegistry((second, first), (second_definition, first_definition))

    assert left.definitions == right.definitions
    assert left.candidates(
        TransitionDomain.WORKFLOW_STATE,
        "draft",
        workflow_namespace=first_definition.namespace,
    ) == (first,)
    assert left.candidates(TransitionDomain.WORKFLOW_STATE, "draft") == ()


def test_legacy_phase_vocabulary_remains_byte_identical() -> None:
    assert tuple(item.value for item in PhaseCode) == tuple(
        f"F{index:02d}" for index in range(1, 16)
    )
    assert tuple(item.value for item in PhaseStatus) == (
        "not_started",
        "eligible",
        "ready",
        "active",
        "blocked",
        "awaiting_approval",
        "in_review",
        "completed",
        "completed_with_conditions",
        "revalidation_pending",
        "reopened",
        "cancelled",
    )
    assert type(WorkflowStateKey.parse("active")).__name__ == "WorkflowStateKey"
    assert type(PhaseStatus.ACTIVE).__name__ == "PhaseStatus"
