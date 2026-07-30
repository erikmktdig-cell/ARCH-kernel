"""Contract execution checks for every documented K07 invariant fixture."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from arch_kernel.contracts import (
    ArtifactId,
    EventId,
    InvariantDefinition,
    InvariantKind,
    PhaseStatus,
    ProjectId,
)
from arch_kernel.kernel import ArchKernelError, InvariantRegistry, evaluate_invariants
from tests.invariant_helpers import (
    FIXTURE_ROOT,
    canonical_registry,
    context,
    definition,
    load_event,
    load_state,
    valid_history,
)

VALID_ROOT = FIXTURE_ROOT / "valid" / "invariants"
INVALID_ROOT = FIXTURE_ROOT / "invalid" / "invariants"


def test_canonical_registry_and_passing_context_fixtures_execute() -> None:
    payload = json.loads((VALID_ROOT / "canonical_registry.json").read_text(encoding="utf-8"))
    definitions = tuple(
        InvariantDefinition.model_validate_json(json.dumps(item)) for item in payload
    )
    manifest = json.loads((VALID_ROOT / "passing_context.json").read_text(encoding="utf-8"))

    result = evaluate_invariants(context(), InvariantRegistry(definitions))

    assert len(definitions) == 9
    assert result.blocking_failure is False
    assert len(result.violations) == manifest["expected_blocking_violations"]


def test_valid_history_and_snapshot_manifests_match_engine_behavior() -> None:
    history_manifest = json.loads((VALID_ROOT / "ordered_history.json").read_text(encoding="utf-8"))
    history_rule = definition(InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY)
    history_result = evaluate_invariants(
        context(history=tuple(reversed(valid_history()))),
        InvariantRegistry((history_rule,)),
    )

    snapshot_manifest = json.loads(
        (VALID_ROOT / "monotonic_snapshots.json").read_text(encoding="utf-8")
    )
    old = load_state()
    new = old.model_copy(
        update={
            "record_version": snapshot_manifest["record_versions"][1],
            "state_version_updated": 2,
        },
        deep=True,
    )
    version_rule = definition(InvariantKind.MONOTONIC_RECORD_VERSIONS)
    version_result = evaluate_invariants(
        context(new, previous_snapshots=(old,)),
        InvariantRegistry((version_rule,)),
    )

    assert len(history_result.violations) == history_manifest["expected_violations"]
    assert len(version_result.violations) == snapshot_manifest["expected_violations"]


def _scenario_result(scenario: str) -> int:
    state = load_state()
    if scenario == "lifecycle_phase_misalignment":
        lifecycle = state.lifecycle.model_copy(update={"status": PhaseStatus.READY})
        state = state.model_copy(update={"lifecycle": lifecycle})
        kind = InvariantKind.LIFECYCLE_PHASE_ALIGNMENT
    elif scenario == "invalid_approved_baseline":
        missing = ArtifactId.from_str("ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1Z")
        state = state.model_copy(update={"active_baseline_artifact_ids": (missing,)})
        kind = InvariantKind.APPROVED_BASELINE_INTEGRITY
    elif scenario == "unsatisfied_mandatory_dependency":
        requirement_id = next(iter(state.requirement_registry))
        requirement = state.requirement_registry[requirement_id].model_copy(
            update={"status": "proposed"}
        )
        state = state.model_copy(update={"requirement_registry": {requirement_id: requirement}})
        kind = InvariantKind.REQUIRED_DEPENDENCY_SATISFACTION
    elif scenario == "untraceable_requirement":
        requirement_id = next(iter(state.requirement_registry))
        requirement = state.requirement_registry[requirement_id].model_copy(
            update={"artifact_ids": ()}
        )
        state = state.model_copy(
            update={
                "requirement_registry": {requirement_id: requirement},
                "dependency_graph": (),
            }
        )
        kind = InvariantKind.REQUIREMENT_TRACEABILITY
    elif scenario == "uncontrolled_critical_risk":
        risk_id = next(iter(state.risk_registry))
        risk = state.risk_registry[risk_id].model_copy(update={"probability": 5, "impact": 5})
        state = state.model_copy(update={"risk_registry": {risk_id: risk}})
        kind = InvariantKind.CRITICAL_RISK_CONTROL
    elif scenario == "duplicate_event_id":
        event = load_event()
        history = (
            event,
            event.model_copy(update={"idempotency_key": "another-key:001"}),
        )
        kind = InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY
        return len(
            evaluate_invariants(
                context(history=history),
                InvariantRegistry((definition(kind),)),
            ).violations
        )
    elif scenario == "duplicate_idempotency_key":
        event = load_event()
        duplicate = event.model_copy(
            update={
                "event_id": EventId.from_str("EVT-01HZX7M3FQ1T2Q9V8Y6K4C2B1H"),
                "occurred_at": event.occurred_at + timedelta(seconds=1),
                "recorded_at": event.recorded_at + timedelta(seconds=1),
            }
        )
        kind = InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY
        return len(
            evaluate_invariants(
                context(history=(event, duplicate)),
                InvariantRegistry((definition(kind),)),
            ).violations
        )
    elif scenario == "missing_or_forward_causation":
        first, second = valid_history()
        forward = first.model_copy(
            update={"correlation_id": second.event_id, "causation_id": second.event_id}
        )
        kind = InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY
        return len(
            evaluate_invariants(
                context(history=(forward, second)),
                InvariantRegistry((definition(kind),)),
            ).violations
        )
    elif scenario == "event_from_another_project":
        event = load_event().model_copy(
            update={"project_id": ProjectId.from_str("PRJ-01HZX7M3FQ1T2Q9V8Y6K4C2B1Z")}
        )
        kind = InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY
        return len(
            evaluate_invariants(
                context(history=(event,)),
                InvariantRegistry((definition(kind),)),
            ).violations
        )
    elif scenario in {
        "decreasing_record_version",
        "changed_content_without_version_increment",
    }:
        previous = state.model_copy(
            update={"record_version": 2} if scenario == "decreasing_record_version" else {}
        )
        if scenario == "changed_content_without_version_increment":
            profile = state.profile.model_copy(update={"project_type": "service"})
            state = state.model_copy(update={"profile": profile})
        kind = InvariantKind.MONOTONIC_RECORD_VERSIONS
        return len(
            evaluate_invariants(
                context(state, previous_snapshots=(previous,)),
                InvariantRegistry((definition(kind),)),
            ).violations
        )
    else:  # pragma: no cover - fixture set assertion guards this dispatch
        raise AssertionError(scenario)
    return len(
        evaluate_invariants(
            context(state),
            InvariantRegistry((definition(kind),)),
        ).violations
    )


def test_every_invalid_fixture_has_one_primary_documented_failure() -> None:
    manifests = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in INVALID_ROOT.glob("*.json")
    }
    assert len(manifests) == 15

    for manifest in manifests.values():
        scenario = manifest["scenario"]
        if scenario == "duplicate_invariant_id":
            first = definition(InvariantKind.SINGLE_ACTIVE_PHASE)
            second = definition(
                InvariantKind.LIFECYCLE_PHASE_ALIGNMENT,
                invariant_id=first.invariant_id,
            )
            with pytest.raises(ArchKernelError):
                InvariantRegistry((first, second))
        elif scenario == "duplicate_invariant_key":
            first = definition(InvariantKind.SINGLE_ACTIVE_PHASE)
            second = definition(
                InvariantKind.LIFECYCLE_PHASE_ALIGNMENT,
                key=first.key,
            )
            with pytest.raises(ArchKernelError):
                InvariantRegistry((first, second))
        elif scenario == "unsupported_configuration":
            with pytest.raises(ArchKernelError):
                InvariantRegistry(
                    (
                        definition(
                            InvariantKind.SINGLE_ACTIVE_PHASE,
                            configuration=manifest["configuration"],
                        ),
                    )
                )
        elif scenario == "unknown_selected_key":
            with pytest.raises(ArchKernelError):
                evaluate_invariants(
                    context(selected_keys=tuple(manifest["selected_keys"])),
                    canonical_registry(),
                )
        else:
            assert _scenario_result(scenario) == manifest["expected_violations"]
