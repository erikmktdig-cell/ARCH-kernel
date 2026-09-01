"""Generic namespaced workflow contracts with no consumer-domain coupling."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, ClassVar, Self

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler, field_validator, model_validator
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

from arch_kernel.contracts._validation import SHA256_FINGERPRINT_RE, require_unique
from arch_kernel.contracts.base import ImmutableRecord, VersionedRecord
from arch_kernel.contracts.ids import WorkflowId
from arch_kernel.contracts.versions import SemanticVersion

_WORKFLOW_NAMESPACE_PATTERN = r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$"
_WORKFLOW_STATE_PATTERN = r"^[A-Za-z][A-Za-z0-9_]*(?:[.-][A-Za-z0-9_]+)*$"
_WORKFLOW_NAMESPACE_RE = re.compile(_WORKFLOW_NAMESPACE_PATTERN, re.ASCII)
_WORKFLOW_STATE_RE = re.compile(_WORKFLOW_STATE_PATTERN, re.ASCII)


@dataclass(frozen=True, slots=True)
class _ValidatedString:
    """Immutable Pydantic-compatible canonical string value."""

    value: str
    pattern: ClassVar[str]
    label: ClassVar[str]

    def __post_init__(self) -> None:
        type(self)._validate(self.value)

    @classmethod
    def _validate(cls, value: object) -> str:
        if not isinstance(value, str) or re.fullmatch(cls.pattern, value, re.ASCII) is None:
            raise ValueError(f"{cls.label} does not match its canonical grammar.")
        return value

    @classmethod
    def parse(cls, value: str) -> Self:
        return cls(cls._validate(value))

    def __str__(self) -> str:
        return self.value

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        from_string = core_schema.no_info_after_validator_function(
            cls.parse,
            core_schema.str_schema(pattern=cls.pattern),
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
        return {"type": "string", "title": cls.__name__, "pattern": cls.pattern}


class WorkflowNamespace(_ValidatedString):
    """Stable owner-qualified key for a downstream workflow definition."""

    pattern = _WORKFLOW_NAMESPACE_PATTERN
    label = "Workflow namespace"


class WorkflowStateKey(_ValidatedString):
    """Case-sensitive state token admitted by one explicit definition."""

    pattern = _WORKFLOW_STATE_PATTERN
    label = "Workflow state"


class WorkflowDefinition(ImmutableRecord):
    """Closed deterministic state space owned by one workflow namespace."""

    workflow_id: WorkflowId
    namespace: WorkflowNamespace
    definition_version: SemanticVersion
    allowed_states: tuple[WorkflowStateKey, ...]
    initial_state: WorkflowStateKey

    @field_validator("allowed_states")
    @classmethod
    def _states_must_be_non_empty_unique_and_canonical(
        cls, value: tuple[WorkflowStateKey, ...]
    ) -> tuple[WorkflowStateKey, ...]:
        if not value:
            raise ValueError("allowed_states cannot be empty.")
        require_unique(value, field_name="allowed_states")
        return tuple(sorted(value, key=str))

    @model_validator(mode="after")
    def _initial_state_must_be_allowed(self) -> Self:
        if self.initial_state not in self.allowed_states:
            raise ValueError("initial_state must belong to allowed_states.")
        return self

    def definition_fingerprint(self) -> str:
        """Return the timestamp-independent identity of this state space."""

        return self.contract_content_fingerprint()


class WorkflowStateRecord(VersionedRecord):
    """Authoritative operational state for one initialized workflow."""

    workflow_id: WorkflowId
    namespace: WorkflowNamespace
    definition_version: SemanticVersion
    definition_fingerprint: str
    current_state: WorkflowStateKey

    @field_validator("definition_fingerprint")
    @classmethod
    def _definition_fingerprint_must_be_canonical(cls, value: str) -> str:
        if SHA256_FINGERPRINT_RE.fullmatch(value) is None:
            raise ValueError("definition_fingerprint must use sha256:<64 lowercase hex> format.")
        return value


__all__ = (
    "WorkflowDefinition",
    "WorkflowNamespace",
    "WorkflowStateKey",
    "WorkflowStateRecord",
)
