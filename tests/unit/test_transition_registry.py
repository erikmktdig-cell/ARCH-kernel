"""Tests for deterministic registry construction and lookup."""

import pytest

from arch_kernel.contracts import (
    EffectType,
    EffectValueSource,
    GuardType,
    PatchPath,
    TransitionDomain,
    TransitionEffect,
    TransitionGuard,
    TransitionId,
)
from arch_kernel.kernel import ArchKernelError, ErrorCode, TransitionRegistry
from tests.transition_helpers import effect


def test_lookup_indexes_and_candidate_order_are_stable() -> None:
    lower = effect(priority=20, key="artifact.approve")
    higher = effect(
        priority=10,
        key="artifact.accept",
        transition_id=TransitionId.from_str("TRN-01HZX7M3FQ1T2Q9V8Y6K4C2B1Q"),
    )
    first = TransitionRegistry((lower, higher))
    second = TransitionRegistry((higher, lower))

    assert first.definitions == second.definitions == (higher, lower)
    assert first.get_by_id(lower.transition_id) == lower
    assert first.get_by_key(higher.transition_key) == higher
    assert first.candidates(TransitionDomain.ARTIFACT_STATUS, "under_review") == (
        higher,
        lower,
    )
    assert first.route_candidates(TransitionDomain.ARTIFACT_STATUS, "under_review", "approved") == (
        higher,
        lower,
    )


def test_duplicate_ids_keys_and_same_priority_ambiguity_are_rejected() -> None:
    first = effect()
    duplicate_id = effect(key="artifact.accept")
    duplicate_key = effect(transition_id=TransitionId.from_str("TRN-01HZX7M3FQ1T2Q9V8Y6K4C2B1R"))
    ambiguous = effect(
        key="artifact.accept",
        transition_id=TransitionId.from_str("TRN-01HZX7M3FQ1T2Q9V8Y6K4C2B1S"),
    )

    for candidate, code in (
        (duplicate_id, ErrorCode.INVALID_TRANSITION_DEFINITION),
        (duplicate_key, ErrorCode.INVALID_TRANSITION_DEFINITION),
        (ambiguous, ErrorCode.AMBIGUOUS_TRANSITION),
    ):
        with pytest.raises(ArchKernelError) as raised:
            TransitionRegistry((first, candidate))
        assert raised.value.detail.code is code


def test_registry_rejects_invalid_states_and_unsupported_domain() -> None:
    invalid_source = effect(source="invented")
    invalid_destination = effect(destination="invented")
    approval = effect(
        domain=TransitionDomain.APPROVAL_DECISION,
        source="deferred",
        destination="approved",
        key="approval.approve",
    )
    for definition, code in (
        (invalid_source, ErrorCode.INVALID_TRANSITION_DEFINITION),
        (invalid_destination, ErrorCode.INVALID_TRANSITION_DEFINITION),
        (approval, ErrorCode.UNSUPPORTED_TRANSITION_DOMAIN),
    ):
        with pytest.raises(ArchKernelError) as raised:
            TransitionRegistry((definition,))
        assert raised.value.detail.code is code


def test_registry_enforces_effect_and_guard_scope() -> None:
    cross_domain = effect(
        effects=(
            TransitionEffect(
                effect_type=EffectType.SET_FIELD,
                path_template="/phases/{entity_id}/status",
                value_source=EffectValueSource.TO_STATE,
            ),
        )
    )
    unsafe_guard = effect(
        guards=(
            TransitionGuard(
                guard_type=GuardType.FIELD_EXISTS,
                path=PatchPath.parse("/unknown/value"),
            ),
        )
    )
    with pytest.raises(ArchKernelError):
        TransitionRegistry((cross_domain,))
    with pytest.raises(ArchKernelError):
        TransitionRegistry((unsafe_guard,))


def test_registry_requires_tuple_and_returns_empty_candidates() -> None:
    with pytest.raises(TypeError):
        TransitionRegistry([])  # type: ignore[arg-type]
    registry = TransitionRegistry(())
    assert registry.get_by_key("missing.key") is None
    assert registry.candidates(TransitionDomain.RISK_STATUS, "open") == ()
