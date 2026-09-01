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
    AnyTransitionDefinition,
    TransitionDefinition,
    TransitionDomain,
    WorkflowTransitionDefinition,
)
from arch_kernel.contracts.workflows import WorkflowDefinition, WorkflowNamespace
from arch_kernel.kernel.errors import ArchKernelError, ErrorCode, ErrorDetail, Severity
from arch_kernel.kernel.path_policy import validate_patch_path_policy
from arch_kernel.kernel.workflow_registry import WorkflowDefinitionRegistry

_SUPPORTED_DOMAINS = frozenset(
    {
        TransitionDomain.PROJECT_LIFECYCLE,
        TransitionDomain.PHASE_STATUS,
        TransitionDomain.ARTIFACT_STATUS,
        TransitionDomain.RISK_STATUS,
        TransitionDomain.REQUIREMENT_STATUS,
        TransitionDomain.WORKFLOW_STATE,
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


def _workflow_state_space(
    definition: WorkflowTransitionDefinition,
    workflows: WorkflowDefinitionRegistry,
) -> frozenset[str]:
    workflow = workflows.get(
        definition.workflow_namespace,
        definition.workflow_definition_version,
    )
    if workflow is None:
        raise _registry_error(
            ErrorCode.INVALID_TRANSITION_DEFINITION,
            "Workflow transition references an unknown workflow definition.",
            definition=definition,
            actual=str(definition.workflow_namespace),
        )
    if workflow.definition_fingerprint() != definition.workflow_definition_fingerprint:
        raise _registry_error(
            ErrorCode.INVALID_TRANSITION_DEFINITION,
            "Workflow transition definition fingerprint does not match its state space.",
            definition=definition,
            expected=workflow.definition_fingerprint(),
            actual=definition.workflow_definition_fingerprint,
        )
    return frozenset(str(state) for state in workflow.allowed_states)


def _validate_definition(
    definition: AnyTransitionDefinition,
    workflows: WorkflowDefinitionRegistry,
) -> None:
    if definition.domain not in _SUPPORTED_DOMAINS:
        raise _registry_error(
            ErrorCode.UNSUPPORTED_TRANSITION_DOMAIN,
            "Transition domain has no executable aggregate record.",
            definition=definition,
            expected=", ".join(sorted(domain.value for domain in _SUPPORTED_DOMAINS)),
            actual=definition.domain.value,
        )
    if definition.domain is TransitionDomain.WORKFLOW_STATE:
        if not isinstance(definition, WorkflowTransitionDefinition):
            raise _registry_error(
                ErrorCode.INVALID_TRANSITION_DEFINITION,
                "workflow_state requires WorkflowTransitionDefinition.",
                definition=definition,
            )
        valid_states = _workflow_state_space(definition, workflows)
    else:
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
        elif definition.domain is TransitionDomain.WORKFLOW_STATE:
            valid_surface = (
                segments == ["workflows", "{entity_id}", "current_state"]
                and effect.effect_type.value == "set_field"
                and effect.value_source is not None
                and effect.value_source.value == "to_state"
            )
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

    definitions: tuple[AnyTransitionDefinition, ...]
    workflow_definitions: WorkflowDefinitionRegistry
    _by_id: Mapping[TransitionId, AnyTransitionDefinition] = field(repr=False)
    _by_key: Mapping[str, AnyTransitionDefinition] = field(repr=False)
    _by_source: Mapping[
        tuple[TransitionDomain, WorkflowNamespace | None, str],
        tuple[AnyTransitionDefinition, ...],
    ] = field(repr=False)
    _by_route: Mapping[
        tuple[TransitionDomain, WorkflowNamespace | None, str, str],
        tuple[AnyTransitionDefinition, ...],
    ] = field(repr=False)

    def __init__(
        self,
        definitions: tuple[AnyTransitionDefinition, ...],
        workflow_definitions: tuple[WorkflowDefinition, ...] = (),
    ) -> None:
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
        workflows = WorkflowDefinitionRegistry(workflow_definitions)
        by_id: dict[TransitionId, AnyTransitionDefinition] = {}
        by_key: dict[str, AnyTransitionDefinition] = {}
        by_source: dict[
            tuple[TransitionDomain, WorkflowNamespace | None, str],
            list[AnyTransitionDefinition],
        ] = {}
        by_route: dict[
            tuple[TransitionDomain, WorkflowNamespace | None, str, str],
            list[AnyTransitionDefinition],
        ] = {}
        for definition in ordered:
            _validate_definition(definition, workflows)
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
            namespace = (
                definition.workflow_namespace
                if isinstance(definition, WorkflowTransitionDefinition)
                else None
            )
            for source in definition.from_states:
                source_key = (definition.domain, namespace, source)
                route_key = (definition.domain, namespace, source, definition.to_state)
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
        object.__setattr__(self, "workflow_definitions", workflows)
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

    def get_by_id(self, transition_id: TransitionId) -> AnyTransitionDefinition | None:
        """Return a definition by canonical ID."""

        return self._by_id.get(transition_id)

    def get_by_key(self, transition_key: str) -> AnyTransitionDefinition | None:
        """Return a definition by canonical dotted key."""

        return self._by_key.get(transition_key)

    def candidates(
        self,
        domain: TransitionDomain,
        source_state: str,
        *,
        workflow_namespace: WorkflowNamespace | None = None,
    ) -> tuple[AnyTransitionDefinition, ...]:
        """Return stable priority-ordered candidates for a source state."""

        return self._by_source.get((domain, workflow_namespace, source_state), ())

    def route_candidates(
        self,
        domain: TransitionDomain,
        source_state: str,
        destination_state: str,
        *,
        workflow_namespace: WorkflowNamespace | None = None,
    ) -> tuple[AnyTransitionDefinition, ...]:
        """Return stable candidates for one source-to-destination route."""

        return self._by_route.get((domain, workflow_namespace, source_state, destination_state), ())


__all__ = ("TransitionRegistry",)
