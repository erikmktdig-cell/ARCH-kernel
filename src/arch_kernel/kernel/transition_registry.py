"""Immutable deterministic registry for declarative transition definitions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import get_args

from arch_kernel.contracts.enums import ApprovalDecision, ArtifactStatus, PhaseStatus
from arch_kernel.contracts.ids import TransitionId
from arch_kernel.contracts.patches import PatchOperationType
from arch_kernel.contracts.requirements import RequirementStatus
from arch_kernel.contracts.risks import RiskStatus
from arch_kernel.contracts.transitions import (
    TransitionDefinition,
    TransitionDomain,
)
from arch_kernel.kernel.errors import ArchKernelError, ErrorCode, ErrorDetail, Severity
from arch_kernel.kernel.path_policy import validate_patch_path_policy

_SUPPORTED_DOMAINS = frozenset(
    {
        TransitionDomain.PROJECT_LIFECYCLE,
        TransitionDomain.PHASE_STATUS,
        TransitionDomain.ARTIFACT_STATUS,
        TransitionDomain.RISK_STATUS,
        TransitionDomain.REQUIREMENT_STATUS,
    }
)
_DOMAIN_STATES: Mapping[TransitionDomain, frozenset[str]] = MappingProxyType(
    {
        TransitionDomain.PROJECT_LIFECYCLE: frozenset(item.value for item in PhaseStatus),
        TransitionDomain.PHASE_STATUS: frozenset(item.value for item in PhaseStatus),
        TransitionDomain.ARTIFACT_STATUS: frozenset(item.value for item in ArtifactStatus),
        TransitionDomain.APPROVAL_DECISION: frozenset(item.value for item in ApprovalDecision),
        TransitionDomain.RISK_STATUS: frozenset(get_args(RiskStatus)),
        TransitionDomain.REQUIREMENT_STATUS: frozenset(get_args(RequirementStatus)),
    }
)


def _registry_error(
    code: ErrorCode,
    message: str,
    *,
    definition: TransitionDefinition | None = None,
    expected: str | None = None,
    actual: str | None = None,
) -> ArchKernelError:
    return ArchKernelError(
        ErrorDetail(
            code=code,
            message=message,
            entity_type="transition_definition",
            entity_id=None if definition is None else str(definition.transition_id),
            expected=expected,
            actual=actual,
            severity=Severity.ERROR,
        )
    )


def _validate_definition(definition: TransitionDefinition) -> None:
    if definition.domain not in _SUPPORTED_DOMAINS:
        raise _registry_error(
            ErrorCode.UNSUPPORTED_TRANSITION_DOMAIN,
            "Transition domain has no executable aggregate record.",
            definition=definition,
            expected=", ".join(sorted(domain.value for domain in _SUPPORTED_DOMAINS)),
            actual=definition.domain.value,
        )
    valid_states = _DOMAIN_STATES[definition.domain]
    invalid_sources = tuple(state for state in definition.from_states if state not in valid_states)
    if invalid_sources:
        raise _registry_error(
            ErrorCode.INVALID_TRANSITION_DEFINITION,
            "Transition contains an invalid source state.",
            definition=definition,
            expected=", ".join(sorted(valid_states)),
            actual=", ".join(invalid_sources),
        )
    if definition.to_state not in valid_states:
        raise _registry_error(
            ErrorCode.INVALID_TRANSITION_DEFINITION,
            "Transition contains an invalid destination state.",
            definition=definition,
            expected=", ".join(sorted(valid_states)),
            actual=definition.to_state,
        )
    for guard in definition.guards:
        if guard.path is not None:
            path_error = validate_patch_path_policy(guard.path, PatchOperationType.TEST)
            if path_error is not None:
                raise _registry_error(
                    ErrorCode.INVALID_TRANSITION_DEFINITION,
                    "Transition guard path is outside the public state path policy.",
                    definition=definition,
                    expected="public ProjectState path",
                    actual=str(guard.path),
                )
    for effect in definition.effects:
        segments = effect.path_template[1:].split("/")
        if definition.domain is TransitionDomain.PROJECT_LIFECYCLE:
            valid_surface = segments[0] == "lifecycle"
        else:
            root = {
                TransitionDomain.PHASE_STATUS: "phases",
                TransitionDomain.ARTIFACT_STATUS: "artifacts",
                TransitionDomain.RISK_STATUS: "risks",
                TransitionDomain.REQUIREMENT_STATUS: "requirements",
            }[definition.domain]
            valid_surface = (
                len(segments) >= 3 and segments[0] == root and segments[1] == "{entity_id}"
            )
        if not valid_surface:
            raise _registry_error(
                ErrorCode.INVALID_TRANSITION_DEFINITION,
                "Transition effect falls outside its domain mutation surface.",
                definition=definition,
                expected=definition.domain.value,
                actual=effect.path_template,
            )


@dataclass(frozen=True, slots=True, init=False)
class TransitionRegistry:
    """Validated immutable transition indexes with stable candidate ordering."""

    definitions: tuple[TransitionDefinition, ...]
    _by_id: Mapping[TransitionId, TransitionDefinition] = field(repr=False)
    _by_key: Mapping[str, TransitionDefinition] = field(repr=False)
    _by_source: Mapping[tuple[TransitionDomain, str], tuple[TransitionDefinition, ...]] = field(
        repr=False
    )
    _by_route: Mapping[tuple[TransitionDomain, str, str], tuple[TransitionDefinition, ...]] = field(
        repr=False
    )

    def __init__(self, definitions: tuple[TransitionDefinition, ...]) -> None:
        if not isinstance(definitions, tuple):
            raise TypeError("TransitionRegistry definitions must be a tuple.")
        ordered = tuple(
            sorted(
                definitions,
                key=lambda item: (
                    item.priority,
                    item.transition_key,
                    str(item.transition_id),
                ),
            )
        )
        by_id: dict[TransitionId, TransitionDefinition] = {}
        by_key: dict[str, TransitionDefinition] = {}
        by_source: dict[tuple[TransitionDomain, str], list[TransitionDefinition]] = {}
        by_route: dict[tuple[TransitionDomain, str, str], list[TransitionDefinition]] = {}
        for definition in ordered:
            _validate_definition(definition)
            if definition.transition_id in by_id:
                raise _registry_error(
                    ErrorCode.INVALID_TRANSITION_DEFINITION,
                    "Duplicate transition ID.",
                    definition=definition,
                    actual=str(definition.transition_id),
                )
            if definition.transition_key in by_key:
                raise _registry_error(
                    ErrorCode.INVALID_TRANSITION_DEFINITION,
                    "Duplicate transition key.",
                    definition=definition,
                    actual=definition.transition_key,
                )
            by_id[definition.transition_id] = definition
            by_key[definition.transition_key] = definition
            for source in definition.from_states:
                source_key = (definition.domain, source)
                route_key = (definition.domain, source, definition.to_state)
                for other in by_route.get(route_key, ()):
                    if other.priority == definition.priority:
                        raise _registry_error(
                            ErrorCode.AMBIGUOUS_TRANSITION,
                            "Same-priority transitions overlap on source and destination.",
                            definition=definition,
                            expected="unique priority for an overlapping route",
                            actual=f"{definition.domain.value}:{source}->{definition.to_state}",
                        )
                by_source.setdefault(source_key, []).append(definition)
                by_route.setdefault(route_key, []).append(definition)

        object.__setattr__(self, "definitions", ordered)
        object.__setattr__(self, "_by_id", MappingProxyType(by_id))
        object.__setattr__(self, "_by_key", MappingProxyType(by_key))
        object.__setattr__(
            self,
            "_by_source",
            MappingProxyType({key: tuple(value) for key, value in by_source.items()}),
        )
        object.__setattr__(
            self,
            "_by_route",
            MappingProxyType({key: tuple(value) for key, value in by_route.items()}),
        )

    def get_by_id(self, transition_id: TransitionId) -> TransitionDefinition | None:
        """Return a definition by canonical ID."""

        return self._by_id.get(transition_id)

    def get_by_key(self, transition_key: str) -> TransitionDefinition | None:
        """Return a definition by canonical dotted key."""

        return self._by_key.get(transition_key)

    def candidates(
        self, domain: TransitionDomain, source_state: str
    ) -> tuple[TransitionDefinition, ...]:
        """Return stable priority-ordered candidates for a source state."""

        return self._by_source.get((domain, source_state), ())

    def route_candidates(
        self,
        domain: TransitionDomain,
        source_state: str,
        destination_state: str,
    ) -> tuple[TransitionDefinition, ...]:
        """Return stable candidates for one source-to-destination route."""

        return self._by_route.get((domain, source_state, destination_state), ())


__all__ = ("TransitionRegistry",)
