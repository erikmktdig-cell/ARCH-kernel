"""Deterministic registry and initialization mechanics for generic workflows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from arch_kernel.contracts.versions import SemanticVersion
from arch_kernel.contracts.workflows import (
    WorkflowDefinition,
    WorkflowNamespace,
    WorkflowStateRecord,
)
from arch_kernel.kernel.time import ensure_utc


@dataclass(frozen=True, slots=True, init=False)
class WorkflowDefinitionRegistry:
    """Immutable indexes for explicitly declared workflow state spaces."""

    definitions: tuple[WorkflowDefinition, ...]
    _by_identity: Mapping[tuple[WorkflowNamespace, SemanticVersion], WorkflowDefinition] = field(
        repr=False
    )

    def __init__(self, definitions: tuple[WorkflowDefinition, ...]) -> None:
        if not isinstance(definitions, tuple):
            raise TypeError("WorkflowDefinitionRegistry definitions must be a tuple.")
        ordered = tuple(
            sorted(
                definitions,
                key=lambda item: (
                    str(item.namespace),
                    item.definition_version,
                    str(item.workflow_id),
                ),
            )
        )
        by_identity: dict[tuple[WorkflowNamespace, SemanticVersion], WorkflowDefinition] = {}
        workflow_ids = set()
        for definition in ordered:
            identity = (definition.namespace, definition.definition_version)
            if identity in by_identity:
                raise ValueError("Duplicate workflow namespace and definition version.")
            if definition.workflow_id in workflow_ids:
                raise ValueError("Duplicate workflow definition ID.")
            by_identity[identity] = definition
            workflow_ids.add(definition.workflow_id)
        object.__setattr__(self, "definitions", ordered)
        object.__setattr__(self, "_by_identity", MappingProxyType(by_identity))

    def get(
        self,
        namespace: WorkflowNamespace,
        definition_version: SemanticVersion,
    ) -> WorkflowDefinition | None:
        """Return the exact declared state space for one versioned namespace."""

        return self._by_identity.get((namespace, definition_version))


def initialize_workflow_state(
    definition: WorkflowDefinition,
    *,
    created_at: datetime,
    state_version_created: int,
) -> WorkflowStateRecord:
    """Create the authoritative initial record from one explicit definition."""

    timestamp = ensure_utc(created_at)
    return WorkflowStateRecord(
        contract_name="workflow_state_record",
        contract_version=SemanticVersion.parse("1.0.0"),
        schema_uri="urn:arch:contracts:workflow_state_record:1.0.0",
        created_at=timestamp,
        updated_at=timestamp,
        record_version=1,
        state_version_created=state_version_created,
        state_version_updated=state_version_created,
        workflow_id=definition.workflow_id,
        namespace=definition.namespace,
        definition_version=definition.definition_version,
        definition_fingerprint=definition.definition_fingerprint(),
        current_state=definition.initial_state,
    )


def workflow_record_matches_definition(
    record: WorkflowStateRecord,
    definition: WorkflowDefinition,
) -> bool:
    """Return whether persisted authority is bound to this exact state space."""

    return (
        record.workflow_id == definition.workflow_id
        and record.namespace == definition.namespace
        and record.definition_version == definition.definition_version
        and record.definition_fingerprint == definition.definition_fingerprint()
        and record.current_state in definition.allowed_states
    )


__all__ = (
    "WorkflowDefinitionRegistry",
    "initialize_workflow_state",
    "workflow_record_matches_definition",
)
