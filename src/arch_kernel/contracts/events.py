"""Immutable event contracts for describing historical kernel facts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum, unique
from typing import Self

from pydantic import field_validator, model_validator

from arch_kernel.contracts.base import ImmutableRecord
from arch_kernel.contracts.ids import EventId, ProjectId
from arch_kernel.contracts.references import TypedReference
from arch_kernel.contracts.versions import SemanticVersion
from arch_kernel.kernel.errors import ErrorCode, ReferenceValidationError
from arch_kernel.kernel.event_validation import (
    FrozenJsonObject,
    validate_event_causality,
    validate_event_temporal_order,
    validate_event_type,
    validate_idempotency_key,
)
from arch_kernel.kernel.time import ensure_utc


@unique
class ActorType(StrEnum):
    """Kinds of actors that may originate an event."""

    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"
    INTEGRATION = "integration"


class EventActor(ImmutableRecord):
    """Strict immutable attribution for an event."""

    actor_type: ActorType
    actor_id: str
    display_name: str | None = None

    @field_validator("actor_id")
    @classmethod
    def _actor_id_must_be_canonical(cls, value: str) -> str:
        if value == "" or len(value) > 200 or value != value.strip():
            raise ValueError(
                "actor_id must contain 1 to 200 characters without surrounding whitespace."
            )
        return value

    @field_validator("display_name")
    @classmethod
    def _display_name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and value.strip() == "":
            raise ValueError("display_name cannot be empty.")
        return value


class EventEnvelope(ImmutableRecord):
    """Immutable envelope for one historical event fact."""

    event_id: EventId
    event_type: str
    project_id: ProjectId
    aggregate: TypedReference
    occurred_at: datetime
    recorded_at: datetime
    actor: EventActor
    correlation_id: EventId | None
    causation_id: EventId | None
    idempotency_key: str
    schema_version: SemanticVersion
    payload: FrozenJsonObject

    @field_validator("event_type")
    @classmethod
    def _event_type_must_be_canonical(cls, value: str) -> str:
        return validate_event_type(value)

    @field_validator("idempotency_key")
    @classmethod
    def _idempotency_key_must_be_canonical(cls, value: str) -> str:
        return validate_idempotency_key(value)

    @field_validator("occurred_at", "recorded_at")
    @classmethod
    def _event_timestamps_must_be_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @model_validator(mode="after")
    def _local_event_relations_must_be_valid(self) -> Self:
        validate_event_temporal_order(self.occurred_at, self.recorded_at)
        validate_event_causality(self.event_id, self.correlation_id, self.causation_id)
        if self.aggregate.target_id == self.event_id:
            raise ReferenceValidationError(
                "aggregate cannot reference the event itself.",
                code=ErrorCode.INVALID_REFERENCE,
                path=("aggregate", "target_id"),
                entity_id=str(self.event_id),
                expected="a non-event aggregate identifier",
                actual=str(self.aggregate.target_id),
            )
        return self


__all__ = ("ActorType", "EventActor", "EventEnvelope", "FrozenJsonObject")
