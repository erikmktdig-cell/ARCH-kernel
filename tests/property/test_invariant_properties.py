"""Property-based determinism and policy checks for WP-K07."""

from __future__ import annotations

from itertools import permutations

from hypothesis import given
from hypothesis import strategies as st

from arch_kernel.contracts import InvariantKind, InvariantSeverity
from arch_kernel.kernel import InvariantRegistry, evaluate_invariants
from tests.invariant_helpers import (
    canonical_definitions,
    context,
    definition,
    load_state,
    state_with_second_phase,
)


def test_registry_order_never_changes_canonical_order() -> None:
    definitions = canonical_definitions()[:4]
    expected = InvariantRegistry(definitions).definitions

    for ordering in permutations(definitions):
        assert InvariantRegistry(ordering).definitions == expected


def test_equivalent_registry_mapping_orders_produce_identical_findings() -> None:
    state = load_state()
    artifacts = dict(reversed(tuple(state.artifact_registry.items())))
    requirements = dict(reversed(tuple(state.requirement_registry.items())))
    reordered = state.model_copy(
        update={
            "artifact_registry": artifacts,
            "requirement_registry": requirements,
        },
        deep=True,
    )
    registry = InvariantRegistry(canonical_definitions())

    first = evaluate_invariants(context(state), registry)
    second = evaluate_invariants(context(reordered), registry)

    assert first.violations == second.violations
    assert first.input_fingerprint == second.input_fingerprint


@given(blocking=st.booleans())
def test_blocking_flag_alone_controls_success(blocking: bool) -> None:
    state, _ = state_with_second_phase(status="active")
    invariant = definition(
        InvariantKind.SINGLE_ACTIVE_PHASE,
        severity=InvariantSeverity.WARNING,
        blocking=blocking,
    )

    result = evaluate_invariants(context(state), InvariantRegistry((invariant,)))

    assert result.blocking_failure is blocking
    assert result.success is (not blocking)


def test_adding_nonblocking_violation_does_not_flip_success() -> None:
    state, _ = state_with_second_phase(status="active")
    invariant = definition(
        InvariantKind.SINGLE_ACTIVE_PHASE,
        severity=InvariantSeverity.INFO,
        blocking=False,
    )

    result = evaluate_invariants(context(state), InvariantRegistry((invariant,)))

    assert result.violations
    assert result.success


@given(previous_version=st.integers(min_value=1, max_value=100))
def test_monotonic_versions_never_violate(previous_version: int) -> None:
    previous = load_state().model_copy(update={"record_version": previous_version})
    current = previous.model_copy(
        update={
            "record_version": previous_version + 1,
            "state_version_updated": previous.state_version_updated + 1,
        }
    )
    invariant = definition(InvariantKind.MONOTONIC_RECORD_VERSIONS)

    result = evaluate_invariants(
        context(current, previous_snapshots=(previous,)),
        InvariantRegistry((invariant,)),
    )

    assert result.violations == ()


@given(previous_version=st.integers(min_value=2, max_value=100))
def test_decreasing_versions_always_violate(previous_version: int) -> None:
    previous = load_state().model_copy(update={"record_version": previous_version})
    current = previous.model_copy(update={"record_version": previous_version - 1})
    invariant = definition(InvariantKind.MONOTONIC_RECORD_VERSIONS)

    result = evaluate_invariants(
        context(current, previous_snapshots=(previous,)),
        InvariantRegistry((invariant,)),
    )

    assert result.violations


def test_repeated_evaluations_are_byte_stable() -> None:
    state = load_state()
    registry = InvariantRegistry(canonical_definitions())
    invariant_context = context(state)

    results = tuple(
        evaluate_invariants(invariant_context, registry).model_dump_json() for _ in range(3)
    )

    assert len(set(results)) == 1
