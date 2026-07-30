"""Metamorphic properties for K07 invariant evaluation."""

from __future__ import annotations

from arch_kernel.contracts import InvariantKind
from arch_kernel.kernel import evaluate_invariants
from arch_kernel.kernel.invariant_registry import InvariantRegistry
from tests.invariant_helpers import context, definition, load_event


def test_blocking_flag_alone_controls_duplicate_event_violation() -> None:
    event = load_event()
    evaluation_context = context(history=(event, event))
    non_blocking = evaluate_invariants(
        evaluation_context,
        InvariantRegistry(
            (
                definition(
                    InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY,
                    blocking=False,
                ),
            )
        ),
    )
    blocking = evaluate_invariants(
        evaluation_context,
        InvariantRegistry(
            (
                definition(
                    InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY,
                    blocking=True,
                ),
            )
        ),
    )

    assert non_blocking.success
    assert non_blocking.violations
    assert not blocking.success
    assert len(blocking.violations) == len(non_blocking.violations)


def test_disabled_invariant_cannot_affect_findings() -> None:
    event = load_event()
    evaluation_context = context(history=(event, event))
    disabled = definition(
        InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY,
        enabled=False,
    )

    result = evaluate_invariants(
        evaluation_context,
        InvariantRegistry((disabled,)),
    )

    assert result.success
    assert result.violations == ()
