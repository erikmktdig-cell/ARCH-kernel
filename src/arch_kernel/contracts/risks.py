"""Risk record contract."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from arch_kernel.contracts._validation import (
    require_non_blank,
    require_optional_non_blank,
    require_unique,
)
from arch_kernel.contracts.base import VersionedRecord
from arch_kernel.contracts.ids import ArtifactId, RequirementId, RiskId

RiskStatus = Literal["open", "mitigating", "accepted", "closed", "materialized"]


class RiskRecord(VersionedRecord):
    """Versioned project risk with a calculated, non-persisted score."""

    risk_id: RiskId
    title: str
    description: str
    probability: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    status: RiskStatus
    owner: str
    mitigation: str | None = None
    related_artifact_ids: tuple[ArtifactId, ...] = Field(default_factory=tuple)
    related_requirement_ids: tuple[RequirementId, ...] = Field(default_factory=tuple)

    @field_validator("title", "description", "owner")
    @classmethod
    def _required_text_must_not_be_blank(cls, value: str, info: object) -> str:
        return require_non_blank(value, field_name=getattr(info, "field_name", "risk text"))

    @field_validator("mitigation")
    @classmethod
    def _mitigation_must_not_be_blank(cls, value: str | None) -> str | None:
        return require_optional_non_blank(value, field_name="mitigation")

    @field_validator("related_artifact_ids", "related_requirement_ids")
    @classmethod
    def _related_ids_must_be_unique(
        cls, value: tuple[object, ...], info: object
    ) -> tuple[object, ...]:
        require_unique(value, field_name=getattr(info, "field_name", "related IDs"))
        return value

    @model_validator(mode="after")
    def _mitigating_risks_require_a_mitigation(self) -> RiskRecord:
        if self.status == "mitigating" and self.mitigation is None:
            raise ValueError("mitigation is required when status is mitigating.")
        return self

    @property
    def score(self) -> int:
        """Return the calculated probability-impact score without persisting it."""

        return self.probability * self.impact


__all__ = ("RiskRecord", "RiskStatus")
