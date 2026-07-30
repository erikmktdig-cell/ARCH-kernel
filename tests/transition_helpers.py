"""Shared deterministic builders for WP-K06 tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from arch_kernel.contracts import (
    AnyCanonicalId,
    ChangeId,
    EffectType,
    EffectValueSource,
    GuardType,
    PatchPath,
    PhaseId,
    ProjectState,
    SemanticVersion,
    TransitionDefinition,
    TransitionDomain,
    TransitionEffect,
    TransitionGuard,
    TransitionId,
    TransitionRequest,
    TransitionTarget,
)
from arch_kernel.kernel import TransitionRegistry
from arch_kernel.kernel.fingerprints import canonicalize_json

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures"
EVALUATED_AT = datetime(2026, 7, 25, 18, 0, tzinfo=UTC)
VERSION = SemanticVersion.parse("1.0.0")
TRANSITION_ID = TransitionId.from_str("TRN-01HZX7M3FQ1T2Q9V8Y6K4C2B1M")
CHANGE_ID = ChangeId.from_str("CHG-01HZX7M3FQ1T2Q9V8Y6K4C2B1N")


def load_state() -> ProjectState:
    return ProjectState.model_validate_json(
        (FIXTURE_ROOT / "valid" / "minimal_project_state.json").read_text(encoding="utf-8")
    )


def artifact_review_state() -> ProjectState:
    document = load_state().model_dump(mode="json")
    document["active_baseline_artifact_ids"] = []
    artifact = next(iter(document["artifact_registry"].values()))
    artifact["status"] = "under_review"
    return ProjectState.model_validate_json(canonicalize_json(document))


def phase_review_state() -> tuple[ProjectState, PhaseId]:
    document = load_state().model_dump(mode="json")
    phase_id = PhaseId.from_str("PHS-01HZX7M3FQ1T2Q9V8Y6K4C2B1P")
    original = next(iter(document["phase_execution_records"].values()))
    phase = dict(original)
    phase.update(
        {
            "phase_id": str(phase_id),
            "phase_code": "F03",
            "status": "in_review",
            "started_at": "2026-07-25T16:00:00Z",
            "artifact_ids": [],
            "requirement_ids": [],
        }
    )
    document["phase_execution_records"][str(phase_id)] = phase
    return ProjectState.model_validate_json(canonicalize_json(document)), phase_id


def effect(
    *,
    domain: TransitionDomain = TransitionDomain.ARTIFACT_STATUS,
    source: str = "under_review",
    destination: str = "approved",
    transition_id: TransitionId = TRANSITION_ID,
    key: str = "artifact.approve",
    guards: tuple[TransitionGuard, ...] = (),
    effects: tuple[TransitionEffect, ...] | None = None,
    priority: int = 100,
    allow_self_transition: bool = False,
) -> TransitionDefinition:
    root = {
        TransitionDomain.PROJECT_LIFECYCLE: "/lifecycle/status",
        TransitionDomain.PHASE_STATUS: "/phases/{entity_id}/status",
        TransitionDomain.ARTIFACT_STATUS: "/artifacts/{entity_id}/status",
        TransitionDomain.RISK_STATUS: "/risks/{entity_id}/status",
        TransitionDomain.REQUIREMENT_STATUS: "/requirements/{entity_id}/status",
        TransitionDomain.APPROVAL_DECISION: "/approvals/{entity_id}/decision",
    }[domain]
    rendered_effects = effects or (
        TransitionEffect(
            effect_type=EffectType.SET_FIELD,
            path_template=root,
            value_source=EffectValueSource.TO_STATE,
        ),
    )
    return TransitionDefinition(
        transition_id=transition_id,
        name=key.replace(".", " ").title(),
        transition_key=key,
        contract_version=VERSION,
        domain=domain,
        from_states=(source,),
        to_state=destination,
        guards=guards,
        effects=rendered_effects,
        priority=priority,
        allow_self_transition=allow_self_transition,
    )


def request(
    state: ProjectState,
    definition: TransitionDefinition,
    *,
    entity_id: AnyCanonicalId | None = None,
    **changes: object,
) -> TransitionRequest:
    selected_id = entity_id
    if selected_id is None:
        selected_id = next(iter(state.artifact_registry))
    values: dict[str, object] = {
        "request_id": CHANGE_ID,
        "project_id": state.metadata.project_id,
        "target": TransitionTarget(domain=definition.domain, entity_id=selected_id),
        "transition_key": definition.transition_key,
        "requested_at": EVALUATED_AT,
        **changes,
    }
    return TransitionRequest.model_validate(values)


def registry(definition: TransitionDefinition) -> TransitionRegistry:
    return TransitionRegistry((definition,))


def field_guard(
    guard_type: GuardType,
    path: str,
    **values: object,
) -> TransitionGuard:
    return TransitionGuard.model_validate(
        {
            "guard_type": guard_type,
            "path": PatchPath.parse(path),
            **values,
        }
    )
