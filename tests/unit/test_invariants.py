"""Contract tests for immutable WP-K07 invariant models."""

from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import (
    InvariantDefinition,
    InvariantEvaluationContext,
    InvariantEvidence,
    InvariantId,
    InvariantKind,
    InvariantScope,
    InvariantSeverity,
)
from tests.invariant_helpers import EVALUATED_AT, context, definition, load_state, valid_history


def test_invariant_id_and_closed_enums_are_stable() -> None:
    assert InvariantId.prefix == "INV"
    assert InvariantId.target_type == "invariant"
    assert tuple(item.value for item in InvariantSeverity) == (
        "info",
        "warning",
        "error",
        "critical",
    )
    assert tuple(item.value for item in InvariantScope) == (
        "project",
        "lifecycle",
        "phase",
        "artifact",
        "requirement",
        "risk",
        "dependency",
        "history",
    )
    assert len(InvariantKind) == 9


def test_definition_is_strict_deeply_immutable_and_round_trips() -> None:
    original = definition(
        InvariantKind.CRITICAL_RISK_CONTROL,
        configuration={"score_threshold": 16, "allowed_statuses": ["accepted"]},
    )
    restored = InvariantDefinition.model_validate_json(original.model_dump_json())

    assert restored == original
    with pytest.raises(TypeError):
        cast(Any, original.configuration)["score_threshold"] = 20
    with pytest.raises(AttributeError):
        cast(Any, original.configuration)["allowed_statuses"].append("closed")
    with pytest.raises(ValidationError):
        InvariantDefinition.model_validate({**original.model_dump(), "unknown": True})


def test_definition_validates_key_text_and_priority() -> None:
    base = definition(InvariantKind.SINGLE_ACTIVE_PHASE).model_dump()
    with pytest.raises(ValidationError):
        InvariantDefinition.model_validate({**base, "key": "single"})
    with pytest.raises(ValidationError):
        InvariantDefinition.model_validate({**base, "title": " "})
    with pytest.raises(ValidationError):
        InvariantDefinition.model_validate({**base, "priority": 10_001})


def test_evidence_is_strict_json_safe_and_immutable() -> None:
    evidence = InvariantEvidence.model_validate(
        {
            "path": "/risks/example/score",
            "observed": {"score": 20, "inputs": [4, 5]},
            "expected": {"maximum": 14},
            "message": "Risk exceeds the threshold.",
        }
    )

    assert evidence.model_dump(mode="json")["observed"] == {
        "score": 20,
        "inputs": [4, 5],
    }
    with pytest.raises(TypeError):
        cast(Any, evidence.observed)["score"] = 1
    with pytest.raises(ValidationError):
        InvariantEvidence(path="relative", observed=1, expected=2)
    with pytest.raises(ValidationError):
        InvariantEvidence.model_validate({"path": "/value", "observed": object(), "expected": None})


def test_context_normalizes_utc_history_order_and_copies_inputs() -> None:
    state = load_state()
    first, second = valid_history()
    offset = timezone(timedelta(hours=-6))
    original_history = [second, first]
    invariant_context = InvariantEvaluationContext.model_validate(
        {
            "state": state,
            "evaluated_at": datetime(2026, 7, 25, 13, 0, tzinfo=offset),
            "history": original_history,
            "previous_snapshots": [],
            "selected_keys": ["project.phase.single_active"],
        }
    )

    original_history.clear()
    state.open_items = ("mutated externally",)

    assert invariant_context.evaluated_at == EVALUATED_AT
    assert tuple(item.event_id for item in invariant_context.history) == (
        first.event_id,
        second.event_id,
    )
    assert invariant_context.state.open_items != state.open_items


def test_context_rejects_naive_time_duplicate_selection_and_snapshot_order() -> None:
    state = load_state()
    newer = state.model_copy(update={"state_version_updated": 2})
    older = state.model_copy(update={"state_version_updated": 1})

    with pytest.raises(ValidationError):
        context(evaluated_at=datetime(2026, 7, 25, 19, 0))
    with pytest.raises(ValidationError):
        context(selected_keys=("same.key.value", "same.key.value"))
    with pytest.raises(ValidationError):
        context(previous_snapshots=(newer, older))
