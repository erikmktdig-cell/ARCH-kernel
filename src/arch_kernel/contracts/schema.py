"""JSON Schema, compatibility, and registry audit result contracts."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import (
    BeforeValidator,
    Field,
    PlainSerializer,
    WithJsonSchema,
    field_validator,
    model_validator,
)
from pydantic.json_schema import JsonSchemaValue

from arch_kernel.contracts._validation import SHA256_FINGERPRINT_RE, require_non_blank
from arch_kernel.contracts.registry import (
    CompatibilityLevel,
    ContractIdentity,
    VersionBump,
    _FrozenStrictModel,
    validate_canonical_contract_name,
)
from arch_kernel.contracts.versions import SemanticVersion
from arch_kernel.kernel.event_validation import (
    FrozenJsonObject,
    FrozenJsonValue,
    freeze_json_value,
    thaw_json,
)

_JSON_SCHEMA: JsonSchemaValue = {
    "anyOf": [
        {"type": "null"},
        {"type": "boolean"},
        {"type": "integer"},
        {"type": "number"},
        {"type": "string"},
        {"type": "array"},
        {"type": "object"},
    ]
}
type SchemaJsonValue = Annotated[
    FrozenJsonValue,
    BeforeValidator(freeze_json_value),
    PlainSerializer(thaw_json, when_used="json"),
    WithJsonSchema(_JSON_SCHEMA),
]


class SchemaArtifact(_FrozenStrictModel):
    canonical_name: str
    version: SemanticVersion
    schema_id: str
    normalized_schema: FrozenJsonObject
    schema_fingerprint: str
    filename: str

    @field_validator("canonical_name")
    @classmethod
    def _name_must_be_canonical(cls, value: str) -> str:
        return validate_canonical_contract_name(value)

    @field_validator("schema_fingerprint")
    @classmethod
    def _fingerprint_must_be_canonical(cls, value: str) -> str:
        if SHA256_FINGERPRINT_RE.fullmatch(value) is None:
            raise ValueError("schema_fingerprint must use sha256:<64 lowercase hex> format.")
        return value


class CompatibilityFinding(_FrozenStrictModel):
    path: str
    code: str
    message: str
    old_value: SchemaJsonValue | None = None
    new_value: SchemaJsonValue | None = None
    breaking: bool

    @field_validator("path")
    @classmethod
    def _path_must_be_absolute(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("Compatibility paths must be absolute.")
        return value

    @field_validator("code", "message")
    @classmethod
    def _text_must_not_be_blank(cls, value: str, info: object) -> str:
        return require_non_blank(value, field_name=getattr(info, "field_name", "finding field"))


class CompatibilityReport(_FrozenStrictModel):
    source: ContractIdentity
    target: ContractIdentity
    level: CompatibilityLevel
    backward_compatible: bool
    forward_compatible: bool
    findings: tuple[CompatibilityFinding, ...]
    minimum_version_bump: VersionBump
    report_fingerprint: str

    @field_validator("report_fingerprint")
    @classmethod
    def _report_fingerprint_must_be_canonical(cls, value: str) -> str:
        if SHA256_FINGERPRINT_RE.fullmatch(value) is None:
            raise ValueError("report_fingerprint must use sha256:<64 lowercase hex> format.")
        return value

    @model_validator(mode="after")
    def _flags_must_match_level(self) -> Self:
        if self.level is CompatibilityLevel.BREAKING:
            if self.backward_compatible:
                raise ValueError("Breaking compatibility cannot be backward-compatible.")
            return self
        expected = {
            CompatibilityLevel.IDENTICAL: (True, True),
            CompatibilityLevel.FULLY_COMPATIBLE: (True, True),
            CompatibilityLevel.BACKWARD_COMPATIBLE: (True, False),
            CompatibilityLevel.FORWARD_COMPATIBLE: (False, True),
            CompatibilityLevel.UNKNOWN: (False, False),
        }[self.level]
        if (self.backward_compatible, self.forward_compatible) != expected:
            raise ValueError("Compatibility flags must match the declared level.")
        return self


class ContractRegistryAuditFinding(_FrozenStrictModel):
    code: str
    message: str
    path: str
    blocking: bool
    source: ContractIdentity | None = None
    target: ContractIdentity | None = None


class ContractRegistryAuditResult(_FrozenStrictModel):
    success: bool
    findings: tuple[ContractRegistryAuditFinding, ...]
    catalog_fingerprint: str
    audited_contract_count: int = Field(ge=0)
    audited_version_pair_count: int = Field(ge=0)

    @field_validator("catalog_fingerprint")
    @classmethod
    def _catalog_fingerprint_must_be_canonical(cls, value: str) -> str:
        if SHA256_FINGERPRINT_RE.fullmatch(value) is None:
            raise ValueError("catalog_fingerprint must use sha256:<64 lowercase hex> format.")
        return value

    @model_validator(mode="after")
    def _success_must_match_findings(self) -> Self:
        if self.success == any(finding.blocking for finding in self.findings):
            raise ValueError("Audit success must be true exactly without blocking findings.")
        return self


__all__ = (
    "CompatibilityFinding",
    "CompatibilityReport",
    "ContractRegistryAuditFinding",
    "ContractRegistryAuditResult",
    "SchemaArtifact",
    "SchemaJsonValue",
)
