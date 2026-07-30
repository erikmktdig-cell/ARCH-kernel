"""Contract checks for valid and invalid WP-K06 fixtures."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import (
    TransitionDefinition,
    TransitionEffect,
    TransitionGuard,
    TransitionRequest,
    TransitionTarget,
)
from arch_kernel.kernel import ArchKernelError, TransitionRegistry, evaluate_transition
from tests.transition_helpers import FIXTURE_ROOT, artifact_review_state, effect, registry, request


def test_canonical_registry_fixture_loads_and_is_deterministic() -> None:
    payload = json.loads(
        (FIXTURE_ROOT / "valid" / "transitions" / "canonical_registry.json").read_text(
            encoding="utf-8"
        )
    )
    definitions = tuple(
        TransitionDefinition.model_validate_json(json.dumps(item)) for item in payload
    )
    transition_registry = TransitionRegistry(definitions)

    assert len(transition_registry.definitions) == 6
    assert {item.transition_key for item in transition_registry.definitions} == {
        "phase.activate",
        "phase.block",
        "phase.complete",
        "artifact.submit_for_review",
        "artifact.approve",
        "artifact.reject",
    }
    assert tuple(item.model_dump_json() for item in transition_registry.definitions) == tuple(
        item.model_dump_json()
        for item in TransitionRegistry(tuple(reversed(definitions))).definitions
    )


@pytest.mark.parametrize(
    "filename",
    ["phase_activation_request.json", "artifact_approval_request.json"],
)
def test_valid_request_fixtures_round_trip(filename: str) -> None:
    request_payload = (FIXTURE_ROOT / "valid" / "transitions" / filename).read_text(
        encoding="utf-8"
    )
    transition_request = TransitionRequest.model_validate_json(request_payload)

    assert (
        TransitionRequest.model_validate_json(transition_request.model_dump_json())
        == transition_request
    )


def test_every_required_invalid_fixture_case_is_present_and_rejected() -> None:
    cases = json.loads(
        (FIXTURE_ROOT / "invalid" / "transitions" / "invalid_cases.json").read_text(
            encoding="utf-8"
        )
    )
    assert {item["case"] for item in cases} == {
        "duplicate_key",
        "same_priority_ambiguity",
        "invalid_source_state",
        "invalid_destination_state",
        "domain_id_mismatch",
        "unsupported_placeholder",
        "invalid_guard_field_combination",
        "effect_outside_domain_scope",
        "unauthorized_self_transition",
        "request_with_neither_selector",
        "request_with_both_selectors",
        "stale_expected_source_state",
    }

    state = artifact_review_state()
    base = effect()
    for item in cases:
        case = item["case"]
        if case in {"duplicate_key", "same_priority_ambiguity"}:
            candidate = TransitionDefinition.model_validate_json(
                json.dumps({**base.model_dump(mode="json"), **item["overrides"]})
            )
            with pytest.raises(ArchKernelError):
                TransitionRegistry((base, candidate))
        elif case in {"invalid_source_state", "invalid_destination_state"}:
            candidate = TransitionDefinition.model_validate_json(
                json.dumps({**base.model_dump(mode="json"), **item["overrides"]})
            )
            with pytest.raises(ArchKernelError):
                TransitionRegistry((candidate,))
        elif case == "domain_id_mismatch":
            with pytest.raises(ValidationError):
                TransitionTarget.model_validate_json(json.dumps(item["target"]))
        elif case == "unsupported_placeholder":
            with pytest.raises(ValidationError):
                TransitionEffect.model_validate_json(json.dumps(item["effect"]))
        elif case == "invalid_guard_field_combination":
            with pytest.raises(ValidationError):
                TransitionGuard.model_validate_json(json.dumps(item["guard"]))
        elif case == "effect_outside_domain_scope":
            candidate = base.model_copy(
                update={
                    "effects": (TransitionEffect.model_validate_json(json.dumps(item["effect"])),)
                }
            )
            with pytest.raises(ArchKernelError):
                TransitionRegistry((candidate,))
        elif case == "unauthorized_self_transition":
            with pytest.raises(ValidationError):
                TransitionDefinition.model_validate_json(
                    json.dumps({**base.model_dump(mode="json"), **item["overrides"]})
                )
        elif case in {
            "request_with_neither_selector",
            "request_with_both_selectors",
        }:
            values = {
                **request(state, base).model_dump(mode="json"),
                **item["request_overrides"],
            }
            with pytest.raises(ValidationError):
                TransitionRequest.model_validate_json(json.dumps(values))
        else:
            stale = request(state, base, **item["request_overrides"])
            assert not evaluate_transition(state, stale, registry(base)).allowed
