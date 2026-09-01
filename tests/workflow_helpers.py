"""Deterministic builders for C01 generic workflow tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from arch_kernel.contracts import (
    ChangeId,
    EffectType,
    EffectValueSource,
    ProjectState,
    SemanticVersion,
    TransitionDomain,
    TransitionEffect,
    TransitionId,
    TransitionRequest,
    TransitionTarget,
    WorkflowDefinition,
    WorkflowId,
    WorkflowNamespace,
    WorkflowStateKey,
    WorkflowTransitionDefinition,
)
from arch_kernel.kernel import initialize_workflow_state
from arch_kernel.kernel.fingerprints import canonicalize_json

FIXTURE = Path(__file__).parents[1] / "fixtures" / "valid" / "minimal_project_state.json"
NOW = datetime(2026, 8, 31, 18, 0, tzinfo=UTC)
VERSION = SemanticVersion.parse("1.0.0")
WORKFLOW_ID = WorkflowId.from_str("WFL-01HZX7M3FQ1T2Q9V8Y6K4C2B1A")


def workflow_definition(
    *,
    namespace: str = "example.delivery",
    states: tuple[str, ...] = ("draft", "approved", "released"),
    initial_state: str = "draft",
) -> WorkflowDefinition:
    return WorkflowDefinition(
        contract_name="workflow_definition",
        contract_version=VERSION,
        schema_uri="urn:arch:contracts:workflow_definition:1.0.0",
        created_at=NOW,
        workflow_id=WORKFLOW_ID,
        namespace=WorkflowNamespace.parse(namespace),
        definition_version=VERSION,
        allowed_states=tuple(WorkflowStateKey.parse(state) for state in states),
        initial_state=WorkflowStateKey.parse(initial_state),
    )


def project_with_workflow(
    definition: WorkflowDefinition | None = None,
) -> tuple[ProjectState, WorkflowDefinition]:
    selected = definition or workflow_definition()
    state = ProjectState.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    record = initialize_workflow_state(
        selected,
        created_at=NOW,
        state_version_created=state.record_version,
    )
    document = state.model_dump(mode="json")
    document["workflow_registry"] = {str(record.workflow_id): record.model_dump(mode="json")}
    return ProjectState.model_validate_json(canonicalize_json(document)), selected


def workflow_transition(
    definition: WorkflowDefinition,
    *,
    source: str = "draft",
    destination: str = "approved",
    transition_id: str = "TRN-01HZX7M3FQ1T2Q9V8Y6K4C2B1A",
    key: str = "workflow.advance",
    effects: tuple[TransitionEffect, ...] | None = None,
    priority: int = 100,
) -> WorkflowTransitionDefinition:
    return WorkflowTransitionDefinition(
        transition_id=TransitionId.from_str(transition_id),
        name="Advance workflow",
        transition_key=key,
        contract_version=VERSION,
        domain=TransitionDomain.WORKFLOW_STATE,
        from_states=(source,),
        to_state=destination,
        effects=effects
        or (
            TransitionEffect(
                effect_type=EffectType.SET_FIELD,
                path_template="/workflows/{entity_id}/current_state",
                value_source=EffectValueSource.TO_STATE,
            ),
        ),
        priority=priority,
        workflow_namespace=definition.namespace,
        workflow_definition_version=definition.definition_version,
        workflow_definition_fingerprint=definition.definition_fingerprint(),
    )


def workflow_request(
    state: ProjectState,
    transition: WorkflowTransitionDefinition,
    **changes: object,
) -> TransitionRequest:
    record = state.workflow_registry[WORKFLOW_ID]
    values: dict[str, object] = {
        "request_id": ChangeId.from_str("CHG-01HZX7M3FQ1T2Q9V8Y6K4C2B1A"),
        "project_id": state.metadata.project_id,
        "target": TransitionTarget(
            domain=TransitionDomain.WORKFLOW_STATE,
            entity_id=WORKFLOW_ID,
        ),
        "transition_key": transition.transition_key,
        "expected_from_state": str(record.current_state),
        "expected_target_record_version": record.record_version,
        "expected_target_content_fingerprint": record.contract_content_fingerprint(),
        "requested_at": NOW,
        **changes,
    }
    return TransitionRequest.model_validate(values)


__all__ = (
    "NOW",
    "VERSION",
    "WORKFLOW_ID",
    "project_with_workflow",
    "workflow_definition",
    "workflow_request",
    "workflow_transition",
)
