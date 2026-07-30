"""Tests for immutable validated invariant registry behavior."""

from dataclasses import FrozenInstanceError

import pytest

from arch_kernel.contracts import (
    InvariantId,
    InvariantKind,
    InvariantScope,
    InvariantSeverity,
)
from arch_kernel.kernel import ArchKernelError, ErrorCode, InvariantRegistry
from tests.invariant_helpers import canonical_definitions, definition


def test_registry_lookup_filter_and_order_are_deterministic() -> None:
    definitions = canonical_definitions()
    registry = InvariantRegistry(tuple(reversed(definitions)))

    assert registry.definitions == definitions
    assert registry.get_by_id(definitions[0].invariant_id) == definitions[0]
    assert registry.get_by_key(definitions[1].key) == definitions[1]
    assert registry.filter(scope=InvariantScope.HISTORY) == definitions[-2:]
    assert registry.filter(kind=InvariantKind.CRITICAL_RISK_CONTROL) == (definitions[5],)
    assert registry.filter(severity=InvariantSeverity.ERROR, enabled=True) == definitions
    assert registry.filter(enabled=False) == ()


def test_registry_rejects_duplicate_ids_and_keys_with_specific_codes() -> None:
    first = definition(InvariantKind.SINGLE_ACTIVE_PHASE)
    duplicate_id = definition(
        InvariantKind.LIFECYCLE_PHASE_ALIGNMENT,
        invariant_id=first.invariant_id,
    )
    duplicate_key = definition(
        InvariantKind.LIFECYCLE_PHASE_ALIGNMENT,
        key=first.key,
    )

    for candidate, code in (
        (duplicate_id, ErrorCode.DUPLICATE_INVARIANT_ID),
        (duplicate_key, ErrorCode.DUPLICATE_INVARIANT_KEY),
    ):
        with pytest.raises(ArchKernelError) as raised:
            InvariantRegistry((first, candidate))
        assert raised.value.detail.code is code


@pytest.mark.parametrize(
    ("kind", "configuration"),
    [
        (InvariantKind.SINGLE_ACTIVE_PHASE, {"unknown": True}),
        (
            InvariantKind.APPROVED_BASELINE_INTEGRITY,
            {"require_content_fingerprint": "yes"},
        ),
        (
            InvariantKind.REQUIRED_DEPENDENCY_SATISFACTION,
            {"source_terminal_states": {"unknown": ["done"]}},
        ),
        (
            InvariantKind.REQUIREMENT_TRACEABILITY,
            {"allowed_target_types": ["external"]},
        ),
        (
            InvariantKind.CRITICAL_RISK_CONTROL,
            {"score_threshold": 26},
        ),
        (
            InvariantKind.TERMINAL_PHASE_CONSISTENCY,
            {"terminal_statuses": ["invented"]},
        ),
        (
            InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY,
            {"require_causation_exists": 1},
        ),
    ],
)
def test_registry_rejects_unsupported_configuration(
    kind: InvariantKind,
    configuration: object,
) -> None:
    with pytest.raises(ArchKernelError) as raised:
        InvariantRegistry((definition(kind, configuration=configuration),))
    assert raised.value.detail.code is ErrorCode.INVALID_INVARIANT_DEFINITION


def test_registry_rejects_kind_scope_mismatch_and_is_frozen() -> None:
    mismatched = definition(
        InvariantKind.CRITICAL_RISK_CONTROL,
        scope=InvariantScope.ARTIFACT,
    )
    with pytest.raises(ArchKernelError):
        InvariantRegistry((mismatched,))

    registry = InvariantRegistry(())
    assert registry.get_by_key("unknown.invariant.key") is None
    with pytest.raises(TypeError):
        InvariantRegistry([])  # type: ignore[arg-type]
    with pytest.raises(FrozenInstanceError):
        registry.definitions = ()  # type: ignore[misc]


def test_registry_priority_key_and_id_are_stable_tie_breakers() -> None:
    first = definition(
        InvariantKind.SINGLE_ACTIVE_PHASE,
        priority=10,
        key="project.phase.alpha",
    )
    second = definition(
        InvariantKind.LIFECYCLE_PHASE_ALIGNMENT,
        priority=10,
        key="project.phase.beta",
        invariant_id=InvariantId.from_str("INV-01HZX7M3FQ1T2Q9V8Y6K4C2B1Z"),
    )
    assert InvariantRegistry((second, first)).definitions == (first, second)
