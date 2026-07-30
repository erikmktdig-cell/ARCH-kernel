"""Immutable deterministic registry for closed K07 invariant definitions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import get_args

from arch_kernel.contracts.decisions import DecisionStatus
from arch_kernel.contracts.enums import ArtifactStatus, PhaseStatus
from arch_kernel.contracts.ids import InvariantId
from arch_kernel.contracts.invariants import (
    InvariantDefinition,
    InvariantKind,
    InvariantScope,
    InvariantSeverity,
)
from arch_kernel.contracts.requirements import RequirementStatus
from arch_kernel.contracts.risks import RiskStatus
from arch_kernel.kernel.errors import ArchKernelError, ErrorCode, ErrorDetail, Severity
from arch_kernel.kernel.event_validation import thaw_json

_EXPECTED_SCOPES: Mapping[InvariantKind, InvariantScope] = MappingProxyType(
    {
        InvariantKind.SINGLE_ACTIVE_PHASE: InvariantScope.PROJECT,
        InvariantKind.LIFECYCLE_PHASE_ALIGNMENT: InvariantScope.LIFECYCLE,
        InvariantKind.APPROVED_BASELINE_INTEGRITY: InvariantScope.ARTIFACT,
        InvariantKind.REQUIRED_DEPENDENCY_SATISFACTION: InvariantScope.DEPENDENCY,
        InvariantKind.REQUIREMENT_TRACEABILITY: InvariantScope.REQUIREMENT,
        InvariantKind.CRITICAL_RISK_CONTROL: InvariantScope.RISK,
        InvariantKind.TERMINAL_PHASE_CONSISTENCY: InvariantScope.PHASE,
        InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY: InvariantScope.HISTORY,
        InvariantKind.MONOTONIC_RECORD_VERSIONS: InvariantScope.HISTORY,
    }
)
_ALLOWED_CONFIG_KEYS: Mapping[InvariantKind, frozenset[str]] = MappingProxyType(
    {
        InvariantKind.SINGLE_ACTIVE_PHASE: frozenset(),
        InvariantKind.LIFECYCLE_PHASE_ALIGNMENT: frozenset(),
        InvariantKind.APPROVED_BASELINE_INTEGRITY: frozenset(
            {"allowed_statuses", "require_content_fingerprint"}
        ),
        InvariantKind.REQUIRED_DEPENDENCY_SATISFACTION: frozenset(
            {"source_terminal_states", "target_satisfied_states"}
        ),
        InvariantKind.REQUIREMENT_TRACEABILITY: frozenset({"statuses", "allowed_target_types"}),
        InvariantKind.CRITICAL_RISK_CONTROL: frozenset({"score_threshold", "allowed_statuses"}),
        InvariantKind.TERMINAL_PHASE_CONSISTENCY: frozenset(
            {"terminal_statuses", "require_completed_at", "require_outputs"}
        ),
        InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY: frozenset({"require_causation_exists"}),
        InvariantKind.MONOTONIC_RECORD_VERSIONS: frozenset(),
    }
)
_REFERENCE_TYPES = frozenset({"project", "phase", "artifact", "requirement", "risk", "decision"})
_STATE_VALUES: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "phase": frozenset(item.value for item in PhaseStatus),
        "artifact": frozenset(item.value for item in ArtifactStatus),
        "requirement": frozenset(get_args(RequirementStatus)),
        "risk": frozenset(get_args(RiskStatus)),
        "decision": frozenset(get_args(DecisionStatus)),
    }
)


def _registry_error(
    code: ErrorCode,
    message: str,
    *,
    definition: InvariantDefinition | None = None,
    expected: str | None = None,
    actual: str | None = None,
) -> ArchKernelError:
    return ArchKernelError(
        ErrorDetail(
            code=code,
            message=message,
            entity_type="invariant_definition",
            entity_id=None if definition is None else str(definition.invariant_id),
            expected=expected,
            actual=actual,
            severity=Severity.ERROR,
        )
    )


def _require_string_tuple(
    configuration: Mapping[str, object],
    key: str,
    *,
    allowed: frozenset[str] | None = None,
) -> None:
    value = configuration.get(key)
    if value is None:
        return
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError(f"{key} must be a non-empty unique JSON array of strings.")
    if allowed is not None and any(item not in allowed for item in value):
        raise ValueError(f"{key} contains an unsupported value.")


def _require_bool(configuration: Mapping[str, object], key: str) -> None:
    value = configuration.get(key)
    if value is not None and type(value) is not bool:
        raise ValueError(f"{key} must be a boolean.")


def _require_state_mapping(configuration: Mapping[str, object], key: str) -> None:
    value = configuration.get(key)
    if value is None:
        return
    if not isinstance(value, dict) or any(item not in _STATE_VALUES for item in value):
        raise ValueError(f"{key} must map supported reference types to state arrays.")
    for target_type, states in value.items():
        if (
            not isinstance(states, list)
            or not states
            or any(not isinstance(state, str) for state in states)
            or len(set(states)) != len(states)
        ):
            raise ValueError(f"{key} state arrays must be non-empty and unique.")
        if any(state not in _STATE_VALUES[target_type] for state in states):
            raise ValueError(f"{key} contains an unsupported state for {target_type}.")


def _validate_configuration(definition: InvariantDefinition) -> None:
    configuration = thaw_json(definition.configuration)
    if not isinstance(configuration, dict):
        raise AssertionError("Invariant configuration must thaw to a JSON object.")
    allowed_keys = _ALLOWED_CONFIG_KEYS[definition.kind]
    unknown = tuple(sorted(set(configuration) - allowed_keys))
    if unknown:
        raise ValueError(f"Unsupported configuration keys: {', '.join(unknown)}.")

    if definition.kind is InvariantKind.APPROVED_BASELINE_INTEGRITY:
        _require_string_tuple(
            configuration,
            "allowed_statuses",
            allowed=frozenset(item.value for item in ArtifactStatus),
        )
        _require_bool(configuration, "require_content_fingerprint")
    elif definition.kind is InvariantKind.REQUIRED_DEPENDENCY_SATISFACTION:
        _require_state_mapping(configuration, "source_terminal_states")
        _require_state_mapping(configuration, "target_satisfied_states")
    elif definition.kind is InvariantKind.REQUIREMENT_TRACEABILITY:
        _require_string_tuple(configuration, "statuses")
        _require_string_tuple(
            configuration,
            "allowed_target_types",
            allowed=_REFERENCE_TYPES,
        )
    elif definition.kind is InvariantKind.CRITICAL_RISK_CONTROL:
        threshold = configuration.get("score_threshold")
        if threshold is not None and (type(threshold) is not int or not 1 <= threshold <= 25):
            raise ValueError("score_threshold must be an integer from 1 through 25.")
        _require_string_tuple(configuration, "allowed_statuses")
    elif definition.kind is InvariantKind.TERMINAL_PHASE_CONSISTENCY:
        _require_string_tuple(
            configuration,
            "terminal_statuses",
            allowed=frozenset(item.value for item in PhaseStatus),
        )
        _require_bool(configuration, "require_completed_at")
        _require_bool(configuration, "require_outputs")
    elif definition.kind is InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY:
        _require_bool(configuration, "require_causation_exists")


def _validate_definition(definition: InvariantDefinition) -> None:
    expected_scope = _EXPECTED_SCOPES[definition.kind]
    if definition.scope is not expected_scope:
        raise _registry_error(
            ErrorCode.INVALID_INVARIANT_DEFINITION,
            "Invariant scope does not match its closed implementation kind.",
            definition=definition,
            expected=expected_scope.value,
            actual=definition.scope.value,
        )
    try:
        _validate_configuration(definition)
    except (AssertionError, ValueError) as error:
        raise _registry_error(
            ErrorCode.INVALID_INVARIANT_DEFINITION,
            "Invariant configuration is invalid.",
            definition=definition,
            expected=", ".join(sorted(_ALLOWED_CONFIG_KEYS[definition.kind])) or "empty object",
            actual=str(error),
        ) from error


@dataclass(frozen=True, slots=True, init=False)
class InvariantRegistry:
    """Validated immutable definitions with stable evaluation ordering."""

    definitions: tuple[InvariantDefinition, ...]
    _by_id: Mapping[InvariantId, InvariantDefinition] = field(repr=False)
    _by_key: Mapping[str, InvariantDefinition] = field(repr=False)

    def __init__(self, definitions: tuple[InvariantDefinition, ...]) -> None:
        if not isinstance(definitions, tuple):
            raise TypeError("InvariantRegistry definitions must be a tuple.")
        ordered = tuple(
            sorted(
                definitions,
                key=lambda item: (
                    item.priority,
                    item.key,
                    str(item.invariant_id),
                ),
            )
        )
        by_id: dict[InvariantId, InvariantDefinition] = {}
        by_key: dict[str, InvariantDefinition] = {}
        for definition in ordered:
            _validate_definition(definition)
            if definition.invariant_id in by_id:
                raise _registry_error(
                    ErrorCode.DUPLICATE_INVARIANT_ID,
                    "Duplicate invariant ID.",
                    definition=definition,
                    actual=str(definition.invariant_id),
                )
            if definition.key in by_key:
                raise _registry_error(
                    ErrorCode.DUPLICATE_INVARIANT_KEY,
                    "Duplicate invariant key.",
                    definition=definition,
                    actual=definition.key,
                )
            by_id[definition.invariant_id] = definition
            by_key[definition.key] = definition
        object.__setattr__(self, "definitions", ordered)
        object.__setattr__(self, "_by_id", MappingProxyType(by_id))
        object.__setattr__(self, "_by_key", MappingProxyType(by_key))

    def get_by_id(self, invariant_id: InvariantId) -> InvariantDefinition | None:
        """Return a definition by canonical ID."""

        return self._by_id.get(invariant_id)

    def get_by_key(self, key: str) -> InvariantDefinition | None:
        """Return a definition by stable dotted key."""

        return self._by_key.get(key)

    def filter(
        self,
        *,
        scope: InvariantScope | None = None,
        severity: InvariantSeverity | None = None,
        kind: InvariantKind | None = None,
        enabled: bool | None = None,
    ) -> tuple[InvariantDefinition, ...]:
        """Return definitions matching every supplied closed filter."""

        return tuple(
            definition
            for definition in self.definitions
            if (scope is None or definition.scope is scope)
            and (severity is None or definition.severity is severity)
            and (kind is None or definition.kind is kind)
            and (enabled is None or definition.enabled is enabled)
        )


__all__ = ("InvariantRegistry",)
