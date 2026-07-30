"""Declarative contracts for atomic ProjectState patch dry runs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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
    require_optional_non_blank,
    require_unique,
)
from arch_kernel.contracts.base import ImmutableRecord
from arch_kernel.contracts.enums import ExecutionStatus
from arch_kernel.contracts.events import EventActor
from arch_kernel.contracts.ids import PatchId, ProjectId
from arch_kernel.contracts.project_state import ProjectState
from arch_kernel.kernel.errors import ErrorDetail
from arch_kernel.kernel.event_validation import (
    FrozenJsonValue,
    freeze_json_value,
    thaw_json,
)

_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$", re.ASCII)
_PATCH_VALUE_SCHEMA: JsonSchemaValue = {
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

type PatchJsonValue = Annotated[
    FrozenJsonValue,
    BeforeValidator(freeze_json_value),
    PlainSerializer(thaw_json, when_used="json"),
    WithJsonSchema(_PATCH_VALUE_SCHEMA),
]


@unique
class PatchOperationType(StrEnum):
    """Operations supported by the WP-K05 patch contract."""

    ADD = "add"
    REPLACE = "replace"
    REMOVE = "remove"
    TEST = "test"


@dataclass(frozen=True, slots=True)
class PatchPath:
    """Canonical immutable path within the public ProjectState patch surface."""

    segments: tuple[str, ...]
    _value: str = field(init=False, repr=False, compare=False)

    pattern: ClassVar[str] = r"^/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*$"

    def __post_init__(self) -> None:
        if not isinstance(self.segments, tuple) or not self.segments:
            raise ValueError("PatchPath requires at least one segment.")
        for segment in self.segments:
            if not isinstance(segment, str) or _PATH_SEGMENT_RE.fullmatch(segment) is None:
                raise ValueError(
                    "PatchPath segments must use safe ASCII letters, digits, '_' or '-'."
                )
            if segment in {".", ".."} or segment.startswith("_") or "__" in segment:
                raise ValueError("PatchPath cannot contain private, dunder, or traversal segments.")
        object.__setattr__(self, "_value", "/" + "/".join(self.segments))

    @classmethod
    def parse(cls, value: str) -> Self:
        """Parse a canonical path without normalization or JSON Pointer escapes."""

        if not isinstance(value, str):
            raise TypeError("PatchPath must be parsed from a string.")
        if value != value.strip():
            raise ValueError("PatchPath cannot contain surrounding whitespace.")
        if "\\" in value or not value.startswith("/") or value == "/" or "//" in value:
            raise ValueError("PatchPath must be an absolute non-empty canonical path.")
        return cls(tuple(value[1:].split("/")))

    def is_within(self, scope: PatchPath) -> bool:
        """Return whether this path is equal to or descends from a scope path."""

        return (
            len(scope.segments) <= len(self.segments)
            and self.segments[: len(scope.segments)] == scope.segments
        )

    def __str__(self) -> str:
        return self._value

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        from_string = core_schema.no_info_after_validator_function(
            cls.parse,
            core_schema.str_schema(),
        )
        return core_schema.json_or_python_schema(
            json_schema=from_string,
            python_schema=core_schema.union_schema(
                [core_schema.is_instance_schema(cls), from_string]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                str,
                return_schema=core_schema.str_schema(),
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        _core_schema: core_schema.CoreSchema,
        _handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        return {
            "type": "string",
            "title": cls.__name__,
            "pattern": cls.pattern,
            "examples": ["/artifacts/ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1C"],
        }


class PatchOperation(BaseModel):
    """One immutable add, replace, remove, or test operation."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    op: PatchOperationType
    path: PatchPath
    value: PatchJsonValue | None = None
    expected_record_version: int | None = Field(default=None, ge=1)
    expected_content_fingerprint: str | None = None

    @field_validator("expected_content_fingerprint")
    @classmethod
    def _expected_fingerprint_must_be_canonical(cls, value: str | None) -> str | None:
        if value is not None and SHA256_FINGERPRINT_RE.fullmatch(value) is None:
            raise ValueError(
                "expected_content_fingerprint must use sha256:<64 lowercase hex> format."
            )
        return value

    @model_validator(mode="after")
    def _value_presence_must_match_operation(self) -> Self:
        value_was_supplied = "value" in self.model_fields_set
        if self.op in {
            PatchOperationType.ADD,
            PatchOperationType.REPLACE,
            PatchOperationType.TEST,
        }:
            if not value_was_supplied:
                raise ValueError(f"{self.op.value} operation requires value.")
        elif value_was_supplied:
            raise ValueError("remove operation does not accept value.")
        return self


class StatePatch(ImmutableRecord):
    """Immutable declaration of an atomic ProjectState change."""

    patch_id: PatchId
    project_id: ProjectId
    base_state_record_version: int = Field(ge=1)
    base_state_content_fingerprint: str
    operations: tuple[PatchOperation, ...] = Field(min_length=1)
    created_by: EventActor
    reason: str | None = None
    scope: tuple[PatchPath, ...] = Field(min_length=1)

    @field_validator("base_state_content_fingerprint")
    @classmethod
    def _base_fingerprint_must_be_canonical(cls, value: str) -> str:
        if SHA256_FINGERPRINT_RE.fullmatch(value) is None:
            raise ValueError(
                "base_state_content_fingerprint must use sha256:<64 lowercase hex> format."
            )
        return value

    @field_validator("reason")
    @classmethod
    def _reason_must_not_be_blank(cls, value: str | None) -> str | None:
        return require_optional_non_blank(value, field_name="reason")

    @model_validator(mode="after")
    def _operations_and_scope_must_be_unambiguous(self) -> Self:
        serialized = tuple(operation.model_dump_json() for operation in self.operations)
        require_unique(serialized, field_name="operations")
        for index, scope_path in enumerate(self.scope):
            if any(
                index != other_index and scope_path.is_within(other_scope)
                for other_index, other_scope in enumerate(self.scope)
            ):
                raise ValueError("scope cannot contain paths covered by another scope path.")
        for operation in self.operations:
            if not any(operation.path.is_within(scope_path) for scope_path in self.scope):
                raise ValueError("Every patch operation must fall within the declared scope.")
        return self


class PatchValidationResult(BaseModel):
    """Immutable deterministic validation report for a state patch."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    is_valid: bool
    errors: tuple[ErrorDetail, ...] = ()
    warnings: tuple[ErrorDetail, ...] = ()

    @model_validator(mode="after")
    def _validity_must_match_errors(self) -> Self:
        if self.is_valid == bool(self.errors):
            raise ValueError("is_valid must be true exactly when errors is empty.")
        return self


class DryRunResult(BaseModel):
    """Immutable outcome of a pure atomic ProjectState patch simulation."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    status: ExecutionStatus
    patch_id: PatchId
    original_state_record_fingerprint: str
    original_state_content_fingerprint: str
    projected_state_record_fingerprint: str | None
    projected_state_content_fingerprint: str | None
    changed_paths: tuple[PatchPath, ...]
    validation: PatchValidationResult
    projected_state: ProjectState | None

    @model_validator(mode="after")
    def _result_shape_must_match_status(self) -> Self:
        is_completed = self.status is ExecutionStatus.COMPLETED
        has_projected_result = (
            self.projected_state is not None
            and self.projected_state_record_fingerprint is not None
            and self.projected_state_content_fingerprint is not None
        )
        if is_completed != has_projected_result:
            raise ValueError("Only completed dry runs may contain a projected state.")
        if is_completed != self.validation.is_valid:
            raise ValueError("Dry-run status must agree with patch validation.")
        if not is_completed and self.changed_paths:
            raise ValueError("Failed dry runs cannot report changed paths.")
        return self


__all__ = (
    "DryRunResult",
    "PatchOperation",
    "PatchOperationType",
    "PatchPath",
    "PatchValidationResult",
    "StatePatch",
)
