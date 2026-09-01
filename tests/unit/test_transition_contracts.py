"""Contract tests for strict immutable transition declarations."""

import json
from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import (
    ArtifactId,
    EffectType,
    EffectValueSource,
    GuardType,
    PatchPath,
    ProjectId,
    TransitionDefinition,
    TransitionDomain,
    TransitionEffect,
    TransitionGuard,
    TransitionId,
    TransitionTarget,
)
from tests.transition_helpers import TRANSITION_ID, effect


def test_transition_id_has_canonical_semantics() -> None:
    assert TransitionId.prefix == "TRN"
    assert TransitionId.target_type == "transition"
    assert str(TRANSITION_ID).startswith("TRN-")


def test_transition_enums_are_stable() -> None:
    assert tuple(item.value for item in TransitionDomain) == (
        "project_lifecycle",
        "phase_status",
        "artifact_status",
        "approval_decision",
        "risk_status",
        "requirement_status",
        "workflow_state",
    )
    assert tuple(item.value for item in GuardType) == (
        "field_equals",
        "field_not_equals",
        "field_in",
        "field_exists",
        "field_absent",
        "reference_exists",
        "no_active_phase_except_target",
        "all_dependencies_satisfied",
    )


def test_definition_is_strict_round_trips_and_deep_freezes_metadata() -> None:
    definition = effect()
    restored = TransitionDefinition.model_validate_json(definition.model_dump_json())

    assert restored == definition
    with pytest.raises(ValidationError):
        TransitionDefinition.model_validate(
            {**definition.model_dump(mode="json"), "unexpected": True}
        )
    with pytest.raises(TypeError):
        definition.metadata["owner"] = "changed"  # type: ignore[index]


def test_definition_rejects_bad_keys_sources_duplicates_and_self_transition() -> None:
    base = effect().model_dump(mode="json")
    with pytest.raises(ValidationError):
        TransitionDefinition.model_validate_json(json.dumps({**base, "transition_key": "Approve"}))
    with pytest.raises(ValidationError):
        TransitionDefinition.model_validate_json(json.dumps({**base, "from_states": ()}))
    with pytest.raises(ValidationError):
        TransitionDefinition.model_validate_json(
            json.dumps({**base, "from_states": ("under_review", "under_review")})
        )
    with pytest.raises(ValidationError):
        TransitionDefinition.model_validate_json(
            json.dumps({**base, "from_states": ("approved",), "to_state": "approved"})
        )
    allowed = TransitionDefinition.model_validate_json(
        json.dumps(
            {
                **base,
                "from_states": ("approved",),
                "to_state": "approved",
                "allow_self_transition": True,
            }
        )
    )
    assert allowed.allow_self_transition


def test_definition_rejects_duplicate_guards_and_effects() -> None:
    guard = TransitionGuard(
        guard_type=GuardType.FIELD_EXISTS,
        path=PatchPath.parse("/profile/project_type"),
    )
    base = effect().model_dump(mode="json")
    with pytest.raises(ValidationError):
        TransitionDefinition.model_validate_json(
            json.dumps(
                {
                    **base,
                    "guards": [
                        guard.model_dump(mode="json"),
                        guard.model_dump(mode="json"),
                    ],
                }
            )
        )
    duplicate_effect = effect().effects[0]
    with pytest.raises(ValidationError):
        TransitionDefinition.model_validate_json(
            json.dumps(
                {
                    **base,
                    "effects": [
                        duplicate_effect.model_dump(mode="json"),
                        duplicate_effect.model_dump(mode="json"),
                    ],
                }
            )
        )


def test_target_rejects_domain_identifier_mismatch() -> None:
    with pytest.raises(ValidationError):
        TransitionTarget(
            domain=TransitionDomain.ARTIFACT_STATUS,
            entity_id=ProjectId.generate(),
        )
    target = TransitionTarget(
        domain=TransitionDomain.ARTIFACT_STATUS,
        entity_id=ArtifactId.generate(),
    )
    with pytest.raises(ValidationError):
        target.entity_id = ArtifactId.generate()


def test_guard_field_combinations_are_closed() -> None:
    path = PatchPath.parse("/profile/project_type")
    assert (
        TransitionGuard(guard_type=GuardType.FIELD_EQUALS, path=path, expected=None).expected
        is None
    )
    with pytest.raises(ValidationError):
        TransitionGuard(guard_type=GuardType.FIELD_EQUALS, path=path)
    with pytest.raises(ValidationError):
        TransitionGuard(guard_type=GuardType.FIELD_IN, path=path)
    with pytest.raises(ValidationError):
        TransitionGuard(
            guard_type=GuardType.FIELD_EXISTS,
            path=path,
            expected="platform",
        )
    with pytest.raises(ValidationError):
        TransitionGuard(guard_type=GuardType.REFERENCE_EXISTS)
    with pytest.raises(ValidationError):
        TransitionGuard(
            guard_type=GuardType.NO_ACTIVE_PHASE_EXCEPT_TARGET,
            path=path,
        )


def test_effect_rejects_bad_sources_placeholders_and_protected_fields() -> None:
    with pytest.raises(ValidationError):
        TransitionEffect(
            effect_type=EffectType.SET_FIELD,
            path_template="/artifacts/{unknown}/status",
            value_source=EffectValueSource.TO_STATE,
        )
    with pytest.raises(ValidationError):
        TransitionEffect(
            effect_type=EffectType.SET_FIELD,
            path_template="/artifacts/{entity_id}/record_version",
            value_source=EffectValueSource.TO_STATE,
        )
    with pytest.raises(ValidationError):
        TransitionEffect(
            effect_type=EffectType.SET_FIELD,
            path_template="/artifacts/{entity_id}/status",
        )
    with pytest.raises(ValidationError):
        TransitionEffect(
            effect_type=EffectType.REMOVE_FIELD,
            path_template="/artifacts/{entity_id}/status",
            value_source=EffectValueSource.LITERAL,
            literal_value=None,
        )
    with pytest.raises(ValidationError):
        TransitionEffect(
            effect_type=EffectType.ASSERT_FIELD,
            path_template="/artifacts/{entity_id}/status",
            value_source=EffectValueSource.LITERAL,
        )


def test_registry_dataclass_is_frozen() -> None:
    from arch_kernel.kernel import TransitionRegistry

    registry = TransitionRegistry((effect(),))
    with pytest.raises(FrozenInstanceError):
        registry.definitions = ()  # type: ignore[misc]
