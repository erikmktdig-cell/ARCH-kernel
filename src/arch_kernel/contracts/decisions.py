"""Immutable decision record contract."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from arch_kernel.contracts._validation import require_non_blank, require_unique
from arch_kernel.contracts.base import ImmutableRecord
from arch_kernel.contracts.ids import ArtifactId, DecisionId, RequirementId

DecisionStatus = Literal["proposed", "accepted", "rejected", "superseded"]


class DecisionRecord(ImmutableRecord):
    """Historical decision retained as a superficially immutable record."""

    decision_id: DecisionId
    title: str
    context: str
    decision: str
    rationale: str
    status: DecisionStatus
    decided_by: str
    decided_at: datetime
    supersedes: DecisionId | None = None
    related_artifact_ids: tuple[ArtifactId, ...] = Field(default_factory=tuple)
    related_requirement_ids: tuple[RequirementId, ...] = Field(default_factory=tuple)

    @field_validator("title", "context", "decision", "rationale", "decided_by")
    @classmethod
    def _required_text_must_not_be_blank(cls, value: str, info: object) -> str:
        return require_non_blank(value, field_name=getattr(info, "field_name", "decision text"))

    @field_validator("related_artifact_ids", "related_requirement_ids")
    @classmethod
    def _related_ids_must_be_unique(
        cls, value: tuple[object, ...], info: object
    ) -> tuple[object, ...]:
        require_unique(value, field_name=getattr(info, "field_name", "related IDs"))
        return value

    @model_validator(mode="after")
    def _decision_must_not_supersede_itself(self) -> Self:
        if self.supersedes == self.decision_id:
            raise ValueError("A decision cannot supersede itself.")
        return self


__all__ = ("DecisionRecord", "DecisionStatus")
