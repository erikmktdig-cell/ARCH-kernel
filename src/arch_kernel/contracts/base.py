"""Strict base models shared by future ARch contract definitions."""

from __future__ import annotations

from datetime import datetime
from typing import Self, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from arch_kernel.contracts.versions import SemanticVersion
from arch_kernel.kernel.fingerprints import (
    canonicalize_json,
    compute_content_fingerprint,
    compute_fingerprint,
)
from arch_kernel.kernel.time import ensure_utc


def _require_non_blank(value: str, *, field_name: str) -> str:
    if value.strip() == "":
        raise ValueError(f"{field_name} cannot be empty.")
    return value


class ContractModel(BaseModel):
    """Strict, mutable base class for canonical contract payloads."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_assignment=True,
        validate_by_name=True,
    )

    contract_name: str
    contract_version: SemanticVersion
    schema_uri: str
    created_at: datetime
    updated_at: datetime | None = None

    @field_validator("contract_name", "schema_uri")
    @classmethod
    def _metadata_must_not_be_blank(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "contract metadata")
        return _require_non_blank(value, field_name=field_name)

    @field_validator("created_at", "updated_at")
    @classmethod
    def _timestamps_must_be_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return ensure_utc(value)

    @model_validator(mode="after")
    def _updated_at_must_not_precede_created_at(self) -> Self:
        if self.updated_at is not None and self.updated_at < self.created_at:
            raise ValueError("updated_at must be greater than or equal to created_at.")
        return self

    def canonical_dict(self) -> dict[str, object]:
        """Return the complete model payload in JSON-compatible form."""

        return cast(dict[str, object], self.model_dump(mode="json", by_alias=False))

    def canonical_json(self) -> bytes:
        """Return the complete model payload as deterministic canonical JSON."""

        return canonicalize_json(self.canonical_dict())

    def fingerprint(self) -> str:
        """Return the stable full-record fingerprint of every serialized field."""

        return compute_fingerprint(self.canonical_dict())

    def record_fingerprint(self) -> str:
        """Return the stable fingerprint of the complete persisted record."""

        return self.fingerprint()

    def contract_content_fingerprint(self) -> str:
        """Return the content fingerprint without root timestamp metadata.

        This excludes only ``created_at`` and ``updated_at``. All other fields,
        including versions, remain part of the fingerprint.
        """

        return compute_content_fingerprint(self.canonical_dict())


class VersionedRecord(ContractModel):
    """Base contract for mutable records versioned inside a project state."""

    record_version: int = Field(ge=1)
    state_version_created: int = Field(ge=0)
    state_version_updated: int = Field(ge=0)

    @model_validator(mode="after")
    def _state_versions_must_be_monotonic(self) -> Self:
        if self.state_version_updated < self.state_version_created:
            raise ValueError(
                "state_version_updated must be greater than or equal to state_version_created."
            )
        return self


class ImmutableRecord(ContractModel):
    """Frozen base contract for historical records.

    Pydantic's ``frozen`` configuration blocks field reassignment, but it does
    not deep-freeze nested lists or dictionaries. Historical record subclasses
    should prefer tuples and nested frozen models for internal collections.
    """

    model_config = ConfigDict(frozen=True)


__all__ = ("ContractModel", "ImmutableRecord", "VersionedRecord")
