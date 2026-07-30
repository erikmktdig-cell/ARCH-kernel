"""Typed and evidence references for canonical contracts."""

from __future__ import annotations

import re
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from arch_kernel.contracts.ids import AnyCanonicalId, target_type_for_id
from arch_kernel.contracts.versions import SemanticVersion
from arch_kernel.kernel.errors import ErrorCode, ReferenceValidationError

_SHA256_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _reject_blank(value: str, *, field_name: str) -> str:
    if value.strip() == "":
        raise ReferenceValidationError(
            f"{field_name} cannot be empty.",
            path=(field_name,),
            expected="non-empty string",
            actual=value,
        )
    return value


class TypedReference(BaseModel):
    """Immutable reference to another canonical object without resolving it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_type: str
    target_id: AnyCanonicalId
    target_version: SemanticVersion | None = None
    relation: str | None = None

    @field_validator("target_type")
    @classmethod
    def _target_type_must_not_be_blank(cls, value: str) -> str:
        return _reject_blank(value, field_name="target_type")

    @field_validator("relation")
    @classmethod
    def _relation_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _reject_blank(value, field_name="relation")

    @model_validator(mode="after")
    def _target_type_must_match_id(self) -> Self:
        expected_target_type = target_type_for_id(self.target_id)
        if self.target_type != expected_target_type:
            raise ReferenceValidationError(
                "Reference target_type does not match the target_id type.",
                code=ErrorCode.REFERENCE_TYPE_MISMATCH,
                path=("target_type",),
                entity_id=str(self.target_id),
                expected=expected_target_type,
                actual=self.target_type,
            )
        return self


class EvidenceReference(BaseModel):
    """Immutable reference to evidence content without fetching or verifying it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: AnyCanonicalId
    evidence_type: str
    uri: str | None = None
    content_ref: str | None = None
    version: SemanticVersion | None = None
    fingerprint: str | None = None
    description: str | None = None

    @field_validator("evidence_type")
    @classmethod
    def _evidence_type_must_not_be_blank(cls, value: str) -> str:
        return _reject_blank(value, field_name="evidence_type")

    @field_validator("uri")
    @classmethod
    def _uri_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _reject_blank(value, field_name="uri")

    @field_validator("content_ref")
    @classmethod
    def _content_ref_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _reject_blank(value, field_name="content_ref")

    @field_validator("fingerprint")
    @classmethod
    def _fingerprint_must_be_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if _SHA256_FINGERPRINT_RE.fullmatch(value) is None:
            raise ReferenceValidationError(
                "Evidence fingerprint must use the documented sha256:<64 lowercase hex> format.",
                path=("fingerprint",),
                expected="sha256:<64 lowercase hex>",
                actual=value,
            )
        return value

    @model_validator(mode="after")
    def _must_have_locator(self) -> Self:
        if self.uri is None and self.content_ref is None:
            raise ReferenceValidationError(
                "EvidenceReference requires at least one locator.",
                path=("uri",),
                expected="uri or content_ref",
                actual="missing",
            )
        return self


__all__ = ("EvidenceReference", "TypedReference")
