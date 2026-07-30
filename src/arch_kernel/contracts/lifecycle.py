"""Lifecycle contracts and phase execution records."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import Field, field_validator, model_validator

from arch_kernel.contracts._validation import (
    TERMINAL_PHASE_STATUSES,
    require_optional_non_blank,
    require_unique,
)
from arch_kernel.contracts.base import ContractModel, VersionedRecord
from arch_kernel.contracts.enums import PhaseCode, PhaseStatus
from arch_kernel.contracts.ids import ArtifactId, PhaseId, RequirementId


def _validate_phase_timing(
    *,
    status: PhaseStatus,
    started_at: datetime | None,
    completed_at: datetime | None,
    blocked_reason: str | None,
) -> None:
    if completed_at is not None and status not in TERMINAL_PHASE_STATUSES:
        raise ValueError("completed_at requires a terminal-compatible phase status.")
    if started_at is not None and completed_at is not None and started_at > completed_at:
        raise ValueError("started_at cannot be later than completed_at.")
    if status is PhaseStatus.BLOCKED and blocked_reason is None:
        raise ValueError("blocked_reason is required when status is blocked.")


class LifecycleState(ContractModel):
    """Current lifecycle position without cross-record validation."""

    current_phase_id: PhaseId | None
    current_phase_code: PhaseCode | None
    status: PhaseStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    blocked_reason: str | None = None

    @field_validator("blocked_reason")
    @classmethod
    def _blocked_reason_must_not_be_blank(cls, value: str | None) -> str | None:
        return require_optional_non_blank(value, field_name="blocked_reason")

    @model_validator(mode="after")
    def _validate_lifecycle(self) -> Self:
        if (self.current_phase_id is None) != (self.current_phase_code is None):
            raise ValueError("current_phase_id and current_phase_code must be provided together.")
        _validate_phase_timing(
            status=self.status,
            started_at=self.started_at,
            completed_at=self.completed_at,
            blocked_reason=self.blocked_reason,
        )
        return self


class PhaseExecutionRecord(VersionedRecord):
    """Versioned execution record for an individual project phase."""

    phase_id: PhaseId
    phase_code: PhaseCode
    status: PhaseStatus
    attempt: int = Field(ge=1)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    blocked_reason: str | None = None
    artifact_ids: tuple[ArtifactId, ...] = Field(default_factory=tuple)
    requirement_ids: tuple[RequirementId, ...] = Field(default_factory=tuple)

    @field_validator("blocked_reason")
    @classmethod
    def _blocked_reason_must_not_be_blank(cls, value: str | None) -> str | None:
        return require_optional_non_blank(value, field_name="blocked_reason")

    @field_validator("artifact_ids", "requirement_ids")
    @classmethod
    def _referenced_ids_must_be_unique(
        cls, value: tuple[object, ...], info: object
    ) -> tuple[object, ...]:
        field_name = getattr(info, "field_name", "referenced IDs")
        require_unique(value, field_name=field_name)
        return value

    @model_validator(mode="after")
    def _validate_phase_execution(self) -> Self:
        _validate_phase_timing(
            status=self.status,
            started_at=self.started_at,
            completed_at=self.completed_at,
            blocked_reason=self.blocked_reason,
        )
        return self


__all__ = ("LifecycleState", "PhaseExecutionRecord")
