"""Project aggregate and its core state contracts."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from arch_kernel.contracts._validation import require_non_blank, require_unique
from arch_kernel.contracts.artifacts import ArtifactRecord
from arch_kernel.contracts.base import ContractModel, VersionedRecord
from arch_kernel.contracts.decisions import DecisionRecord
from arch_kernel.contracts.dependencies import DependencyEdge
from arch_kernel.contracts.enums import ArtifactStatus, PhaseStatus, Route
from arch_kernel.contracts.ids import (
    ArtifactId,
    PhaseId,
    ProjectId,
    RequirementId,
    RiskId,
)
from arch_kernel.contracts.lifecycle import LifecycleState, PhaseExecutionRecord
from arch_kernel.contracts.requirements import RequirementRecord
from arch_kernel.contracts.risks import RiskRecord

_PROJECT_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ProjectCriticality = Literal["low", "medium", "high", "critical"]


class ProjectMetadata(ContractModel):
    """Human and system identifiers for a project aggregate."""

    project_id: ProjectId
    name: str
    slug: str
    summary: str | None = None
    owner: str
    updated_at: datetime

    @field_validator("name", "owner")
    @classmethod
    def _required_text_must_not_be_blank(cls, value: str, info: object) -> str:
        return require_non_blank(value, field_name=getattr(info, "field_name", "project text"))

    @field_validator("slug")
    @classmethod
    def _slug_must_be_lowercase_kebab_case(cls, value: str) -> str:
        if _PROJECT_SLUG_RE.fullmatch(value) is None:
            raise ValueError("slug must use lowercase kebab-case.")
        return value


class ProjectProfile(ContractModel):
    """Project categorization and immutable planning inputs."""

    project_type: str
    criticality: ProjectCriticality
    default_route: Route
    objectives: tuple[str, ...] = Field(default_factory=tuple)
    constraints: tuple[str, ...] = Field(default_factory=tuple)
    success_criteria: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("project_type")
    @classmethod
    def _project_type_must_not_be_blank(cls, value: str) -> str:
        return require_non_blank(value, field_name="project_type")

    @field_validator("objectives", "constraints", "success_criteria")
    @classmethod
    def _planning_collections_must_be_non_blank_and_unique(
        cls, value: tuple[str, ...], info: object
    ) -> tuple[str, ...]:
        field_name = getattr(info, "field_name", "planning collection")
        for item in value:
            require_non_blank(item, field_name=field_name)
        require_unique(value, field_name=field_name)
        return value


def _contains_identifier(keys: Iterable[object], identifier: object) -> bool:
    return any(str(key) == str(identifier) for key in keys)


class ProjectState(VersionedRecord):
    """Minimal project aggregate with deterministic intra-aggregate validation."""

    metadata: ProjectMetadata
    profile: ProjectProfile
    lifecycle: LifecycleState
    phase_execution_records: dict[PhaseId, PhaseExecutionRecord] = Field(default_factory=dict)
    artifact_registry: dict[ArtifactId, ArtifactRecord] = Field(default_factory=dict)
    requirement_registry: dict[RequirementId, RequirementRecord] = Field(default_factory=dict)
    risk_registry: dict[RiskId, RiskRecord] = Field(default_factory=dict)
    decision_log: tuple[DecisionRecord, ...] = Field(default_factory=tuple)
    dependency_graph: tuple[DependencyEdge, ...] = Field(default_factory=tuple)
    active_baseline_artifact_ids: tuple[ArtifactId, ...] = Field(default_factory=tuple)
    open_items: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("active_baseline_artifact_ids", "open_items")
    @classmethod
    def _aggregate_collections_must_be_unique(
        cls, value: tuple[object, ...], info: object
    ) -> tuple[object, ...]:
        require_unique(value, field_name=getattr(info, "field_name", "aggregate collection"))
        return value

    @model_validator(mode="after")
    def _validate_intra_aggregate_references(self) -> Self:
        for phase_id, phase_record in self.phase_execution_records.items():
            if phase_id != phase_record.phase_id:
                raise ValueError("phase_execution_records key must match record.phase_id.")
        for artifact_id, artifact_record in self.artifact_registry.items():
            if artifact_id != artifact_record.artifact_id:
                raise ValueError("artifact_registry key must match record.artifact_id.")
        for requirement_id, requirement_record in self.requirement_registry.items():
            if requirement_id != requirement_record.requirement_id:
                raise ValueError("requirement_registry key must match record.requirement_id.")
        for risk_id, risk_record in self.risk_registry.items():
            if risk_id != risk_record.risk_id:
                raise ValueError("risk_registry key must match record.risk_id.")

        active_phase_records = [
            record
            for record in self.phase_execution_records.values()
            if record.status is PhaseStatus.ACTIVE
        ]
        if len(active_phase_records) > 1:
            raise ValueError("ProjectState cannot contain more than one active phase record.")

        current_phase_id = self.lifecycle.current_phase_id
        if current_phase_id is None:
            if active_phase_records:
                raise ValueError("An active phase record requires lifecycle.current_phase_id.")
        else:
            current_record = self.phase_execution_records.get(current_phase_id)
            if current_record is None:
                raise ValueError(
                    "lifecycle.current_phase_id must exist in phase_execution_records."
                )
            if current_record.phase_code != self.lifecycle.current_phase_code:
                raise ValueError("Lifecycle phase code must match the current phase record.")
            if current_record.status != self.lifecycle.status:
                raise ValueError("Lifecycle status must match the current phase record.")

        for artifact_id in self.active_baseline_artifact_ids:
            artifact = self.artifact_registry.get(artifact_id)
            if artifact is None:
                raise ValueError("Active baseline artifacts must exist in artifact_registry.")
            if artifact.status not in {
                ArtifactStatus.APPROVED,
                ArtifactStatus.CONDITIONALLY_APPROVED,
            }:
                raise ValueError(
                    "Active baselines require approved or conditionally approved artifacts."
                )

        for phase_record in self.phase_execution_records.values():
            for artifact_id in phase_record.artifact_ids:
                if artifact_id not in self.artifact_registry:
                    raise ValueError("Phase artifact_ids must exist in artifact_registry.")
            for requirement_id in phase_record.requirement_ids:
                if requirement_id not in self.requirement_registry:
                    raise ValueError("Phase requirement_ids must exist in requirement_registry.")

        for requirement in self.requirement_registry.values():
            for artifact_id in requirement.artifact_ids:
                if artifact_id not in self.artifact_registry:
                    raise ValueError("Requirement artifact_ids must exist in artifact_registry.")
        for risk in self.risk_registry.values():
            self._validate_related_ids(risk.related_artifact_ids, risk.related_requirement_ids)
        decision_ids = tuple(decision.decision_id for decision in self.decision_log)
        require_unique(decision_ids, field_name="decision_log decision IDs")
        for decision in self.decision_log:
            self._validate_related_ids(
                decision.related_artifact_ids,
                decision.related_requirement_ids,
            )

        serialized_edges = tuple(edge.canonical_json() for edge in self.dependency_graph)
        require_unique(serialized_edges, field_name="dependency_graph")
        for edge in self.dependency_graph:
            self._validate_dependency_reference(edge.source.target_type, edge.source.target_id)
            self._validate_dependency_reference(edge.target.target_type, edge.target.target_id)

        return self

    def _validate_related_ids(
        self,
        artifact_ids: tuple[ArtifactId, ...],
        requirement_ids: tuple[RequirementId, ...],
    ) -> None:
        if any(artifact_id not in self.artifact_registry for artifact_id in artifact_ids):
            raise ValueError("Related artifact IDs must exist in artifact_registry.")
        if any(
            requirement_id not in self.requirement_registry for requirement_id in requirement_ids
        ):
            raise ValueError("Related requirement IDs must exist in requirement_registry.")

    def _validate_dependency_reference(self, target_type: str, target_id: object) -> None:
        registry_keys: Iterable[object] | None = None
        if target_type == "artifact":
            registry_keys = self.artifact_registry
        elif target_type == "requirement":
            registry_keys = self.requirement_registry
        elif target_type == "risk":
            registry_keys = self.risk_registry
        elif target_type == "decision":
            registry_keys = (decision.decision_id for decision in self.decision_log)
        elif target_type == "phase":
            registry_keys = self.phase_execution_records
        if registry_keys is not None and not _contains_identifier(registry_keys, target_id):
            raise ValueError("DependencyEdge references an entity absent from ProjectState.")


__all__ = (
    "ProjectCriticality",
    "ProjectMetadata",
    "ProjectProfile",
    "ProjectState",
)
