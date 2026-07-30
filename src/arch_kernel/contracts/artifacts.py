"""Artifact record contract."""

from __future__ import annotations

from typing import Self

from pydantic import Field, field_validator, model_validator

from arch_kernel.contracts._validation import (
    SHA256_FINGERPRINT_RE,
    require_non_blank,
    require_unique,
)
from arch_kernel.contracts.base import VersionedRecord
from arch_kernel.contracts.enums import ArtifactStatus
from arch_kernel.contracts.ids import ArtifactId
from arch_kernel.contracts.references import EvidenceReference
from arch_kernel.contracts.versions import SemanticVersion


class ArtifactRecord(VersionedRecord):
    """Versioned metadata and traceability information for an artifact."""

    artifact_id: ArtifactId
    name: str
    artifact_type: str
    status: ArtifactStatus
    owner: str
    version: SemanticVersion
    content_uri: str | None = None
    content_fingerprint: str | None = None
    evidence: tuple[EvidenceReference, ...] = Field(default_factory=tuple)
    supersedes: ArtifactId | None = None
    superseded_by: ArtifactId | None = None

    @field_validator("name", "artifact_type", "owner")
    @classmethod
    def _required_text_must_not_be_blank(cls, value: str, info: object) -> str:
        return require_non_blank(value, field_name=getattr(info, "field_name", "artifact text"))

    @field_validator("content_fingerprint")
    @classmethod
    def _content_fingerprint_must_be_sha256(cls, value: str | None) -> str | None:
        if value is not None and SHA256_FINGERPRINT_RE.fullmatch(value) is None:
            raise ValueError("content_fingerprint must use sha256:<64 lowercase hex> format.")
        return value

    @field_validator("evidence")
    @classmethod
    def _evidence_must_be_unique(
        cls, value: tuple[EvidenceReference, ...]
    ) -> tuple[EvidenceReference, ...]:
        require_unique(value, field_name="evidence")
        return value

    @model_validator(mode="after")
    def _artifact_must_not_supersede_itself(self) -> Self:
        if self.supersedes == self.artifact_id or self.superseded_by == self.artifact_id:
            raise ValueError("An artifact cannot supersede itself.")
        return self


__all__ = ("ArtifactRecord",)
