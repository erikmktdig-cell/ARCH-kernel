"""Strict immutable contracts for the WP-K10 migration framework."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum, unique
from typing import Annotated, Any, ClassVar, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    GetJsonSchemaHandler,
    PlainSerializer,
    WithJsonSchema,
    field_validator,
    model_validator,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

from arch_kernel.contracts._validation import (
    SHA256_FINGERPRINT_RE,
    require_non_blank,
    require_unique,
)
from arch_kernel.contracts.ids import MigrationId
from arch_kernel.contracts.registry import validate_canonical_contract_name
from arch_kernel.contracts.versions import SemanticVersion
from arch_kernel.kernel.errors import Severity
from arch_kernel.kernel.event_validation import (
    FrozenJsonObject,
    FrozenJsonValue,
    freeze_json_value,
    thaw_json,
)
from arch_kernel.kernel.fingerprints import compute_fingerprint
from arch_kernel.kernel.time import ensure_utc

_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$", re.ASCII)
_KEY_RE = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_]*)+$", re.ASCII)
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
type MigrationJsonValue = Annotated[
    FrozenJsonValue,
    BeforeValidator(freeze_json_value),
    PlainSerializer(thaw_json, when_used="json"),
    WithJsonSchema(_JSON_SCHEMA),
]


@unique
class MigrationStatus(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RESERVED = "reserved"


@unique
class MigrationDirection(StrEnum):
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"


@unique
class MigrationOperationType(StrEnum):
    ADD = "add"
    REMOVE = "remove"
    REPLACE = "replace"
    MOVE = "move"
    COPY = "copy"
    RENAME = "rename"
    TEST = "test"
    SET_DEFAULT = "set_default"
    MAP_ENUM = "map_enum"
    COERCE = "coerce"


@unique
class MigrationCoercion(StrEnum):
    INTEGER_TO_NUMBER = "integer_to_number"
    NUMBER_TO_STRING = "number_to_string"
    INTEGER_TO_STRING = "integer_to_string"
    BOOLEAN_TO_STRING = "boolean_to_string"
    STRING_TO_INTEGER = "string_to_integer"
    STRING_TO_NUMBER = "string_to_number"
    STRING_TO_BOOLEAN = "string_to_boolean"


@unique
class MigrationDisposition(StrEnum):
    SUCCEEDED = "succeeded"
    SUCCEEDED_WITH_FINDINGS = "succeeded_with_findings"
    FAILED = "failed"
    NOT_REQUIRED = "not_required"
    NOT_EVALUATED = "not_evaluated"


class _FrozenStrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ContractVersionRef(_FrozenStrictModel):
    canonical_name: str
    version: SemanticVersion

    @field_validator("canonical_name")
    @classmethod
    def _name_must_be_canonical(cls, value: str) -> str:
        return validate_canonical_contract_name(value)


@dataclass(frozen=True, slots=True)
class MigrationPath:
    segments: tuple[str, ...]
    _value: str = field(init=False, repr=False, compare=False)
    pattern: ClassVar[str] = r"^/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*$"

    def __post_init__(self) -> None:
        if not isinstance(self.segments, tuple) or not self.segments:
            raise ValueError("MigrationPath requires at least one segment.")
        for segment in self.segments:
            if (
                not isinstance(segment, str)
                or _SEGMENT_RE.fullmatch(segment) is None
                or segment in {".", ".."}
                or segment.startswith("_")
                or "__" in segment
            ):
                raise ValueError("MigrationPath contains an unsafe segment.")
        object.__setattr__(self, "_value", "/" + "/".join(self.segments))

    @classmethod
    def parse(cls, value: str) -> Self:
        if (
            not isinstance(value, str)
            or value != value.strip()
            or not value.startswith("/")
            or value == "/"
            or "\\" in value
            or "//" in value
        ):
            raise ValueError("MigrationPath must be an absolute canonical path.")
        return cls(tuple(value[1:].split("/")))

    def __str__(self) -> str:
        return self._value

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        from_string = core_schema.no_info_after_validator_function(
            cls.parse, core_schema.str_schema()
        )
        return core_schema.json_or_python_schema(
            json_schema=from_string,
            python_schema=core_schema.union_schema(
                [core_schema.is_instance_schema(cls), from_string]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(str),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        _core_schema: core_schema.CoreSchema,
        _handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        return {"type": "string", "pattern": cls.pattern, "title": cls.__name__}


class MigrationOperation(_FrozenStrictModel):
    operation_type: MigrationOperationType
    path: MigrationPath | None = None
    from_path: MigrationPath | None = None
    value: MigrationJsonValue | None = None
    expected_value: MigrationJsonValue | None = None
    enum_mapping: FrozenJsonObject | None = None
    coercion: MigrationCoercion | None = None
    enum_passthrough: bool = False
    note: str | None = None

    @field_validator("note")
    @classmethod
    def _note_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_non_blank(value, field_name="note")

    @model_validator(mode="after")
    def _shape_must_match_operation(self) -> Self:
        supplied = self.model_fields_set
        op = self.operation_type
        if self.path is None:
            raise ValueError("Every migration operation requires path.")
        if op in {
            MigrationOperationType.MOVE,
            MigrationOperationType.COPY,
            MigrationOperationType.RENAME,
        }:
            if self.from_path is None:
                raise ValueError(f"{op.value} requires from_path.")
            if op is MigrationOperationType.RENAME and (
                self.from_path.segments[:-1] != self.path.segments[:-1]
            ):
                raise ValueError("rename paths must belong to the same object.")
        elif self.from_path is not None:
            raise ValueError(f"{op.value} does not accept from_path.")
        if op in {MigrationOperationType.ADD, MigrationOperationType.REPLACE}:
            if "value" not in supplied:
                raise ValueError(f"{op.value} requires value.")
        elif op is MigrationOperationType.SET_DEFAULT:
            if "value" not in supplied:
                raise ValueError("set_default requires value.")
        elif "value" in supplied:
            raise ValueError(f"{op.value} does not accept value.")
        if op is MigrationOperationType.TEST:
            if "expected_value" not in supplied:
                raise ValueError("test requires expected_value.")
        elif "expected_value" in supplied:
            raise ValueError(f"{op.value} does not accept expected_value.")
        if (op is MigrationOperationType.MAP_ENUM) != (self.enum_mapping is not None):
            raise ValueError("map_enum requires enum_mapping and other operations forbid it.")
        if (op is MigrationOperationType.COERCE) != (self.coercion is not None):
            raise ValueError("coerce requires coercion and other operations forbid it.")
        if self.enum_passthrough and op is not MigrationOperationType.MAP_ENUM:
            raise ValueError("enum_passthrough is valid only for map_enum.")
        return self


class MigrationDefinition(_FrozenStrictModel):
    migration_id: MigrationId
    key: str
    title: str
    description: str
    canonical_name: str
    source_version: SemanticVersion
    target_version: SemanticVersion
    direction: MigrationDirection
    status: MigrationStatus
    priority: int = Field(ge=-10_000, le=10_000)
    operations: tuple[MigrationOperation, ...]
    identity: bool = False
    lossless: bool
    reversible: bool
    reverse_migration_id: MigrationId | None = None
    source_schema_fingerprint: str | None = None
    target_schema_fingerprint: str | None = None
    notes: str | None = None
    remediation_hint: str | None = None
    contract_version: SemanticVersion
    schema_uri: str

    @field_validator("key")
    @classmethod
    def _key_must_be_canonical(cls, value: str) -> str:
        if _KEY_RE.fullmatch(value) is None:
            raise ValueError("Migration key must use lowercase dotted grammar.")
        return value

    @field_validator("canonical_name")
    @classmethod
    def _name_must_be_canonical(cls, value: str) -> str:
        return validate_canonical_contract_name(value)

    @field_validator("title", "description", "schema_uri")
    @classmethod
    def _required_text_must_not_be_blank(cls, value: str, info: object) -> str:
        return require_non_blank(value, field_name=getattr(info, "field_name", "text"))

    @field_validator("notes", "remediation_hint")
    @classmethod
    def _optional_text_must_not_be_blank(cls, value: str | None, info: object) -> str | None:
        if value is None:
            return None
        return require_non_blank(value, field_name=getattr(info, "field_name", "text"))

    @field_validator("source_schema_fingerprint", "target_schema_fingerprint")
    @classmethod
    def _fingerprints_must_be_canonical(cls, value: str | None) -> str | None:
        if value is not None and SHA256_FINGERPRINT_RE.fullmatch(value) is None:
            raise ValueError("Schema fingerprints must use sha256:<64 lowercase hex>.")
        return value

    @model_validator(mode="after")
    def _versions_direction_and_reverse_must_agree(self) -> Self:
        if self.source_version == self.target_version:
            raise ValueError("Migration endpoints must differ.")
        expected = (
            MigrationDirection.UPGRADE
            if self.target_version > self.source_version
            else MigrationDirection.DOWNGRADE
        )
        if self.direction is not expected:
            raise ValueError("Migration direction does not match endpoint versions.")
        if not self.operations and not self.identity:
            raise ValueError("Empty operations require identity=True.")
        if self.operations and self.identity:
            raise ValueError("Identity migrations cannot contain operations.")
        if self.reversible != (self.reverse_migration_id is not None):
            raise ValueError("reversible must agree with reverse_migration_id presence.")
        return self

    def semantic_fingerprint(self) -> str:
        return compute_fingerprint(self)


class MigrationPolicy(_FrozenStrictModel):
    validate_source: bool = True
    validate_each_step: bool = False
    validate_target: bool = True
    allow_deprecated: bool = False
    allow_downgrade: bool = False
    allow_mixed_direction: bool = False
    require_lossless: bool = False
    require_reversible: bool = False
    stop_on_non_blocking_findings: bool = False
    expose_intermediate_payloads: bool = False
    maximum_steps: int = Field(default=32, ge=0, le=1_000)
    enum_passthrough: bool = False


class MigrationRequest(_FrozenStrictModel):
    canonical_name: str
    source_version: SemanticVersion
    target_version: SemanticVersion
    source_payload: FrozenJsonObject
    selected_migration_ids: tuple[MigrationId, ...] | None = None
    selected_migration_keys: tuple[str, ...] | None = None
    expected_source_payload_fingerprint: str | None = None
    expected_registry_fingerprint: str | None = None
    evaluated_at: datetime
    policy: MigrationPolicy = Field(default_factory=MigrationPolicy)

    @field_validator("canonical_name")
    @classmethod
    def _name_must_be_canonical(cls, value: str) -> str:
        return validate_canonical_contract_name(value)

    @field_validator("evaluated_at")
    @classmethod
    def _time_must_be_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator(
        "expected_source_payload_fingerprint",
        "expected_registry_fingerprint",
    )
    @classmethod
    def _fingerprints_must_be_canonical(cls, value: str | None) -> str | None:
        if value is not None and SHA256_FINGERPRINT_RE.fullmatch(value) is None:
            raise ValueError("Expected fingerprints must use sha256:<64 lowercase hex>.")
        return value

    @field_validator("selected_migration_ids", "selected_migration_keys")
    @classmethod
    def _selections_must_be_unique(cls, value: tuple[Any, ...] | None) -> tuple[Any, ...] | None:
        if value is not None:
            require_unique(value, field_name="migration selection")
        return value


class MigrationFinding(_FrozenStrictModel):
    code: str
    message: str
    severity: Severity
    blocking: bool
    path: str | None = None
    expected: MigrationJsonValue | None = None
    actual: MigrationJsonValue | None = None
    remediation_hint: str | None = None
    sequence: int = Field(ge=1)


class MigrationStepResult(_FrozenStrictModel):
    migration_id: MigrationId
    key: str
    source_version: SemanticVersion
    target_version: SemanticVersion
    success: bool
    blocking_failure: bool
    findings: tuple[MigrationFinding, ...]
    input_fingerprint: str
    output_fingerprint: str | None
    changed_paths: tuple[MigrationPath, ...]
    output_payload: FrozenJsonObject | None = None
    sequence: int = Field(ge=1)


class MigrationPlan(_FrozenStrictModel):
    canonical_name: str
    source_version: SemanticVersion
    target_version: SemanticVersion
    migration_ids: tuple[MigrationId, ...]
    version_path: tuple[SemanticVersion, ...]
    total_steps: int = Field(ge=0)
    direction: MigrationDirection | None
    lossless: bool
    reversible: bool
    registry_fingerprint: str
    plan_fingerprint: str


class MigrationResult(_FrozenStrictModel):
    disposition: MigrationDisposition
    success: bool
    blocking_failure: bool
    request_fingerprint: str
    plan: MigrationPlan | None
    step_results: tuple[MigrationStepResult, ...]
    findings: tuple[MigrationFinding, ...]
    final_payload: FrozenJsonObject | None
    source_payload_fingerprint: str
    final_payload_fingerprint: str | None
    source_schema_fingerprint: str | None
    target_schema_fingerprint: str | None
    target_validated: bool
    evaluated_at: datetime
    result_fingerprint: str


class MigrationRegistryAuditResult(_FrozenStrictModel):
    success: bool
    findings: tuple[MigrationFinding, ...]
    registry_fingerprint: str
    audited_migration_count: int = Field(ge=0)
    audited_route_count: int = Field(ge=0)


__all__ = (
    "ContractVersionRef",
    "MigrationCoercion",
    "MigrationDefinition",
    "MigrationDirection",
    "MigrationDisposition",
    "MigrationFinding",
    "MigrationJsonValue",
    "MigrationOperation",
    "MigrationOperationType",
    "MigrationPath",
    "MigrationPlan",
    "MigrationPolicy",
    "MigrationRegistryAuditResult",
    "MigrationRequest",
    "MigrationResult",
    "MigrationStatus",
    "MigrationStepResult",
)
