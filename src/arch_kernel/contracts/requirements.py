"""Requirement record contract."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from arch_kernel.contracts._validation import require_non_blank, require_unique
from arch_kernel.contracts.base import VersionedRecord
from arch_kernel.contracts.ids import ArtifactId, RequirementId

RequirementPriority = Literal["must", "should", "could", "wont"]
RequirementStatus = Literal[
    "proposed",
    "accepted",
    "implemented",
    "verified",
    "rejected",
    "deferred",
]


class RequirementRecord(VersionedRecord):
    """Versioned requirement and its artifact traceability links."""

    requirement_id: RequirementId
    title: str
    description: str
    priority: RequirementPriority
    status: RequirementStatus
    source: str | None = None
    acceptance_criteria: tuple[str, ...] = Field(default_factory=tuple)
    artifact_ids: tuple[ArtifactId, ...] = Field(default_factory=tuple)

    @field_validator("title", "description")
    @classmethod
    def _required_text_must_not_be_blank(cls, value: str, info: object) -> str:
        return require_non_blank(value, field_name=getattr(info, "field_name", "requirement text"))

    @field_validator("source")
    @classmethod
    def _source_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_non_blank(value, field_name="source")

    @field_validator("acceptance_criteria")
    @classmethod
    def _acceptance_criteria_must_be_non_blank_and_unique(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        for criterion in value:
            require_non_blank(criterion, field_name="acceptance_criteria")
        require_unique(value, field_name="acceptance_criteria")
        return value

    @field_validator("artifact_ids")
    @classmethod
    def _artifact_ids_must_be_unique(cls, value: tuple[ArtifactId, ...]) -> tuple[ArtifactId, ...]:
        require_unique(value, field_name="artifact_ids")
        return value


__all__ = ("RequirementPriority", "RequirementRecord", "RequirementStatus")
