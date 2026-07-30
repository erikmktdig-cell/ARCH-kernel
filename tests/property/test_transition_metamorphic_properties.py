"""Metamorphic properties for K06 transition evaluation."""

from __future__ import annotations

import pytest

from arch_kernel.contracts import TransitionId
from arch_kernel.kernel import apply_state_patch_dry_run, evaluate_transition
from arch_kernel.kernel.errors import ArchKernelError, ErrorCode
from arch_kernel.kernel.transition_registry import TransitionRegistry
from tests.transition_helpers import (
    artifact_review_state,
    effect,
    registry,
    request,
)


def test_successful_transition_agrees_with_one_direct_k05_application() -> None:
    state = artifact_review_state()
    definition = effect()
    transition_request = request(state, definition)
    result = evaluate_transition(state, transition_request, registry(definition))

    assert result.allowed
    assert result.state_patch is not None
    direct = apply_state_patch_dry_run(state, result.state_patch)
    assert result.dry_run_result == direct


def test_irrelevant_lower_priority_candidate_does_not_change_selection() -> None:
    state = artifact_review_state()
    selected = effect(priority=100)
    lower = effect(
        transition_id=TransitionId.from_str("TRN-01HZX7M3FQ1T2Q9V8Y6K4C2B1Q"),
        key="artifact.approve_fallback",
        priority=10,
    )
    transition_request = request(state, selected)

    baseline = evaluate_transition(state, transition_request, registry(selected))
    expanded = evaluate_transition(
        state,
        transition_request,
        TransitionRegistry((lower, selected)),
    )

    assert baseline.allowed
    assert expanded.allowed
    assert baseline.transition == expanded.transition
    assert baseline.dry_run_result == expanded.dry_run_result


def test_equal_priority_candidate_fails_closed_as_ambiguity() -> None:
    selected = effect(priority=100)
    equal = effect(
        transition_id=TransitionId.from_str("TRN-01HZX7M3FQ1T2Q9V8Y6K4C2B1Q"),
        key="artifact.approve_equal",
        priority=100,
    )

    with pytest.raises(ArchKernelError) as captured:
        TransitionRegistry((selected, equal))

    assert captured.value.detail.code is ErrorCode.AMBIGUOUS_TRANSITION
