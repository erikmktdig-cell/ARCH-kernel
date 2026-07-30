"""Immutable contract catalog models for WP-K09."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from arch_kernel.contracts._validation import (
    SHA256_FINGERPRINT_RE,
    require_non_blank,
    require_unique,
)
from arch_kernel.contracts.versions import SemanticVersion
from arch_kernel.kernel.event_validation import FrozenJsonObject, freeze_json_object
from arch_kernel.kernel.fingerprints import compute_fingerprint

_CANONICAL_NAME_RE = re.compile(
    r"^arch\.[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$",
    re.ASCII,
)
_PYTHON_PATH_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$",
    re.ASCII,
)
_SCHEMA_ID_RE = re.compile(
    r"^https://schemas\.arch\.local/arch\.[a-z][a-z0-9_.]*/"
    r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$",
    re.ASCII,
)
_SCHEMA_FILENAME_RE = re.compile(
    r"^contracts/arch\.[a-z][a-z0-9_.]*\."
    r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.schema\.json$",
    re.ASCII,
)


def validate_canonical_contract_name(value: str) -> str:
    """Validate and preserve one stable registry identity."""

    if _CANONICAL_NAME_RE.fullmatch(value) is None:
        raise ValueError(
            "Contract names must use arch.<domain>.<contract_name> lowercase ASCII grammar."
        )
    return value


@unique
class ContractKind(StrEnum):
    PRIMITIVE = "primitive"
    RECORD = "record"
    AGGREGATE = "aggregate"
    EVENT = "event"
    COMMAND = "command"
    RESULT = "result"
    REGISTRY = "registry"
    POLICY = "policy"
    DIAGNOSTIC = "diagnostic"


@unique
class ContractStatus(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RESERVED = "reserved"
    INTERNAL = "internal"


@unique
class CompatibilityLevel(StrEnum):
    IDENTICAL = "identical"
    BACKWARD_COMPATIBLE = "backward_compatible"
    FORWARD_COMPATIBLE = "forward_compatible"
    FULLY_COMPATIBLE = "fully_compatible"
    BREAKING = "breaking"
    UNKNOWN = "unknown"


@unique
class VersionBump(StrEnum):
    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"
    MANUAL_REVIEW = "manual_review"


class _FrozenStrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ContractIdentity(_FrozenStrictModel):
    canonical_name: str
    version: SemanticVersion

    @field_validator("canonical_name")
    @classmethod
    def _name_must_be_canonical(cls, value: str) -> str:
        return validate_canonical_contract_name(value)


class ContractAlias(_FrozenStrictModel):
    alias: str
    deprecated_since: SemanticVersion | None = None
    removal_version: SemanticVersion | None = None
    note: str | None = None

    @field_validator("alias")
    @classmethod
    def _alias_must_be_canonical(cls, value: str) -> str:
        return validate_canonical_contract_name(value)

    @field_validator("note")
    @classmethod
    def _note_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_non_blank(value, field_name="note")

    @model_validator(mode="after")
    def _removal_must_follow_deprecation(self) -> Self:
        if self.removal_version is not None and self.deprecated_since is None:
            raise ValueError("Alias removal_version requires deprecated_since.")
        if (
            self.removal_version is not None
            and self.deprecated_since is not None
            and self.removal_version <= self.deprecated_since
        ):
            raise ValueError("Alias removal_version must be greater than deprecated_since.")
        return self


class ContractDescriptor(_FrozenStrictModel):
    canonical_name: str
    version: SemanticVersion
    kind: ContractKind
    status: ContractStatus
    python_module: str
    python_qualname: str
    schema_id: str
    schema_filename: str
    title: str | None = None
    description: str | None = None
    aliases: tuple[ContractAlias, ...] = ()
    replaces: ContractIdentity | None = None
    deprecated_since: SemanticVersion | None = None
    removal_version: SemanticVersion | None = None
    compatibility_notes: str | None = None
    tags: tuple[str, ...] = ()
    model_fingerprint: str
    schema_fingerprint: str
    descriptor_version: SemanticVersion

    @field_validator("canonical_name")
    @classmethod
    def _canonical_name_must_be_valid(cls, value: str) -> str:
        return validate_canonical_contract_name(value)

    @field_validator("python_module", "python_qualname")
    @classmethod
    def _python_identity_must_be_static(cls, value: str) -> str:
        if _PYTHON_PATH_RE.fullmatch(value) is None:
            raise ValueError("Python model identity must use a dotted identifier path.")
        return value

    @field_validator("schema_id")
    @classmethod
    def _schema_id_must_be_local_and_deterministic(cls, value: str) -> str:
        if _SCHEMA_ID_RE.fullmatch(value) is None:
            raise ValueError("schema_id must use the canonical schemas.arch.local URL.")
        return value

    @field_validator("schema_filename")
    @classmethod
    def _schema_filename_must_be_deterministic(cls, value: str) -> str:
        if _SCHEMA_FILENAME_RE.fullmatch(value) is None:
            raise ValueError("schema_filename must use contracts/<name>.<version>.schema.json.")
        return value

    @field_validator("title", "description", "compatibility_notes")
    @classmethod
    def _optional_text_must_not_be_blank(cls, value: str | None, info: object) -> str | None:
        if value is None:
            return None
        return require_non_blank(value, field_name=getattr(info, "field_name", "text"))

    @field_validator("model_fingerprint", "schema_fingerprint")
    @classmethod
    def _fingerprints_must_be_canonical(cls, value: str) -> str:
        if SHA256_FINGERPRINT_RE.fullmatch(value) is None:
            raise ValueError("Fingerprints must use sha256:<64 lowercase hex> format.")
        return value

    @field_validator("tags")
    @classmethod
    def _tags_must_be_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for tag in value:
            if re.fullmatch(r"^[a-z][a-z0-9_-]*$", tag, re.ASCII) is None:
                raise ValueError("Tags must use canonical lowercase ASCII tokens.")
        require_unique(value, field_name="tags")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def _identity_and_lifecycle_must_be_consistent(self) -> Self:
        expected_id = f"https://schemas.arch.local/{self.canonical_name}/{self.version}"
        expected_filename = f"contracts/{self.canonical_name}.{self.version}.schema.json"
        if self.schema_id != expected_id or self.schema_filename != expected_filename:
            raise ValueError("Schema identity and filename must derive from contract identity.")
        aliases = tuple(alias.alias for alias in self.aliases)
        require_unique(aliases, field_name="aliases")
        if self.canonical_name in aliases:
            raise ValueError("An alias cannot equal the canonical contract name.")
        if self.status is ContractStatus.DEPRECATED and self.deprecated_since is None:
            raise ValueError("Deprecated descriptors require deprecated_since.")
        if self.removal_version is not None and self.deprecated_since is None:
            raise ValueError("removal_version requires deprecated_since.")
        if (
            self.removal_version is not None
            and self.deprecated_since is not None
            and self.removal_version <= self.deprecated_since
        ):
            raise ValueError("removal_version must be greater than deprecated_since.")
        return self

    def semantic_fingerprint(self) -> str:
        """Fingerprint every serialized descriptor field."""

        return compute_fingerprint(self)


@dataclass(frozen=True, slots=True)
class ContractRegistration:
    """Runtime-only binding between a descriptor and explicit Pydantic model."""

    descriptor: ContractDescriptor
    model: type[BaseModel]

    def __post_init__(self) -> None:
        if not isinstance(self.descriptor, ContractDescriptor):
            raise TypeError("descriptor must be a ContractDescriptor.")
        if not isinstance(self.model, type) or not issubclass(self.model, BaseModel):
            raise TypeError("model must be an explicit Pydantic BaseModel type.")


class ContractRegistryManifest(_FrozenStrictModel):
    registry_format_version: SemanticVersion
    descriptors: tuple[ContractDescriptor, ...]
    catalog_fingerprint: str
    schema_dialect: str
    generator_identity: str
    generator_version: SemanticVersion
    build_metadata: FrozenJsonObject = Field(default_factory=lambda: freeze_json_object({}))

    @field_validator("catalog_fingerprint")
    @classmethod
    def _catalog_fingerprint_must_be_canonical(cls, value: str) -> str:
        if SHA256_FINGERPRINT_RE.fullmatch(value) is None:
            raise ValueError("catalog_fingerprint must use sha256:<64 lowercase hex> format.")
        return value

    @field_validator("schema_dialect", "generator_identity")
    @classmethod
    def _manifest_text_must_not_be_blank(cls, value: str, info: object) -> str:
        return require_non_blank(value, field_name=getattr(info, "field_name", "manifest field"))

    @model_validator(mode="after")
    def _catalog_fingerprint_must_match_descriptors(self) -> Self:
        expected = compute_fingerprint(
            tuple(
                {
                    "canonical_name": descriptor.canonical_name,
                    "version": str(descriptor.version),
                    "descriptor_fingerprint": descriptor.semantic_fingerprint(),
                    "schema_fingerprint": descriptor.schema_fingerprint,
                }
                for descriptor in self.descriptors
            )
        )
        if self.catalog_fingerprint != expected:
            raise ValueError("catalog_fingerprint must match the ordered descriptors.")
        return self

    def semantic_fingerprint(self) -> str:
        """Fingerprint the manifest while excluding non-semantic build metadata."""

        return compute_fingerprint(self, exclude_fields={"build_metadata"})


__all__ = (
    "CompatibilityLevel",
    "ContractAlias",
    "ContractDescriptor",
    "ContractIdentity",
    "ContractKind",
    "ContractRegistration",
    "ContractRegistryManifest",
    "ContractStatus",
    "VersionBump",
    "validate_canonical_contract_name",
)
