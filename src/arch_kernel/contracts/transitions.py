"""Strict declarative contracts for WP-K06 state transitions."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum, unique
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    WithJsonSchema,
    field_validator,
    model_validator,
)
from pydantic.json_schema import JsonSchemaValue

from arch_kernel.contracts._validation import SHA256_FINGERPRINT_RE, require_non_blank
from arch_kernel.contracts.ids import (
    AnyCanonicalId,
    ApprovalId,
    ArtifactId,
    ChangeId,
    PatchId,
    PhaseId,
    ProjectId,
    RequirementId,
    RiskId,
    TransitionId,
    WorkflowId,
)
from arch_kernel.contracts.patches import DryRunResult, PatchPath, StatePatch
from arch_kernel.contracts.references import TypedReference
from arch_kernel.contracts.versions import SemanticVersion
from arch_kernel.contracts.workflows import WorkflowNamespace
from arch_kernel.kernel.errors import ErrorCode, ErrorDetail, ReferenceValidationError
from arch_kernel.kernel.event_validation import (
    FrozenJsonObject,
    FrozenJsonValue,
    freeze_json_object,
    freeze_json_value,
    thaw_json,
)
from arch_kernel.kernel.fingerprints import canonicalize_json
from arch_kernel.kernel.time import ensure_utc

_TRANSITION_KEY_RE = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_]*)+$", re.ASCII)
_TEMPLATE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$", re.ASCII)
_PLACEHOLDER_RE = re.compile(r"\{[^{}]+\}")
_SUPPORTED_PLACEHOLDERS = {
    "{project_id}",
    "{entity_id}",
    "{evaluated_at}",
    "{to_state}",
}
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

type TransitionJsonValue = Annotated[
    FrozenJsonValue,
    BeforeValidator(freeze_json_value),
    PlainSerializer(thaw_json, when_used="json"),
    WithJsonSchema(_JSON_SCHEMA),
]


@unique
class TransitionDomain(StrEnum):
    """Closed domain names admitted by transition definitions."""

    PROJECT_LIFECYCLE = "project_lifecycle"
    PHASE_STATUS = "phase_status"
    ARTIFACT_STATUS = "artifact_status"
    APPROVAL_DECISION = "approval_decision"
    RISK_STATUS = "risk_status"
    REQUIREMENT_STATUS = "requirement_status"
    WORKFLOW_STATE = "workflow_state"


@unique
class GuardType(StrEnum):
    """Declarative guard operations supported by K06."""

    FIELD_EQUALS = "field_equals"
    FIELD_NOT_EQUALS = "field_not_equals"
    FIELD_IN = "field_in"
    FIELD_EXISTS = "field_exists"
    FIELD_ABSENT = "field_absent"
    REFERENCE_EXISTS = "reference_exists"
    NO_ACTIVE_PHASE_EXCEPT_TARGET = "no_active_phase_except_target"
    ALL_DEPENDENCIES_SATISFIED = "all_dependencies_satisfied"


@unique
class EffectType(StrEnum):
    """Declarative effects that map directly to K05 operations."""

    SET_FIELD = "set_field"
    REMOVE_FIELD = "remove_field"
    ASSERT_FIELD = "assert_field"


@unique
class EffectValueSource(StrEnum):
    """Closed sources from which an effect value may be rendered."""

    LITERAL = "literal"
    TO_STATE = "to_state"
    EVALUATED_AT = "evaluated_at"
    ENTITY_ID = "entity_id"


class _FrozenStrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class TransitionTarget(_FrozenStrictModel):
    """Typed target whose ID must agree with its transition domain."""

    domain: TransitionDomain
    entity_id: AnyCanonicalId

    @model_validator(mode="after")
    def _domain_must_match_identifier(self) -> Self:
        expected_types = {
            TransitionDomain.PROJECT_LIFECYCLE: ProjectId,
            TransitionDomain.PHASE_STATUS: PhaseId,
            TransitionDomain.ARTIFACT_STATUS: ArtifactId,
            TransitionDomain.APPROVAL_DECISION: ApprovalId,
            TransitionDomain.RISK_STATUS: RiskId,
            TransitionDomain.REQUIREMENT_STATUS: RequirementId,
            TransitionDomain.WORKFLOW_STATE: WorkflowId,
        }
        expected_type = expected_types[self.domain]
        if not isinstance(self.entity_id, expected_type):
            raise ReferenceValidationError(
                "Transition target domain does not match its canonical ID type.",
                code=ErrorCode.REFERENCE_TYPE_MISMATCH,
                path=("entity_id",),
                entity_type="transition_target",
                entity_id=str(self.entity_id),
                expected=expected_type.__name__,
                actual=type(self.entity_id).__name__,
            )
        return self


class TransitionGuard(_FrozenStrictModel):
    """One declarative, side-effect-free transition precondition."""

    guard_type: GuardType
    path: PatchPath | None = None
    expected: TransitionJsonValue | None = None
    allowed_values: tuple[TransitionJsonValue, ...] = ()
    reference: TypedReference | None = None
    message: str | None = None

    @field_validator("message")
    @classmethod
    def _message_must_not_be_blank(cls, value: str | None) -> str | None:
        return None if value is None else require_non_blank(value, field_name="message")

    @model_validator(mode="after")
    def _fields_must_match_guard_type(self) -> Self:
        expected_supplied = "expected" in self.model_fields_set
        path_types = {
            GuardType.FIELD_EQUALS,
            GuardType.FIELD_NOT_EQUALS,
            GuardType.FIELD_IN,
            GuardType.FIELD_EXISTS,
            GuardType.FIELD_ABSENT,
        }
        if (self.guard_type in path_types) != (self.path is not None):
            raise ValueError(f"{self.guard_type.value} has an invalid path combination.")
        if self.guard_type in {GuardType.FIELD_EQUALS, GuardType.FIELD_NOT_EQUALS}:
            if not expected_supplied or self.allowed_values or self.reference is not None:
                raise ValueError(f"{self.guard_type.value} requires only expected and path.")
        elif self.guard_type is GuardType.FIELD_IN:
            if expected_supplied or not self.allowed_values or self.reference is not None:
                raise ValueError("field_in requires path and non-empty allowed_values.")
            serialized = tuple(canonicalize_json(thaw_json(value)) for value in self.allowed_values)
            if len(set(serialized)) != len(serialized):
                raise ValueError("allowed_values must be canonically unique.")
        elif self.guard_type in {GuardType.FIELD_EXISTS, GuardType.FIELD_ABSENT}:
            if expected_supplied or self.allowed_values or self.reference is not None:
                raise ValueError(f"{self.guard_type.value} accepts only path.")
        elif self.guard_type is GuardType.REFERENCE_EXISTS:
            if (
                self.reference is None
                or self.path is not None
                or expected_supplied
                or self.allowed_values
            ):
                raise ValueError("reference_exists requires only reference.")
        elif (
            self.path is not None
            or expected_supplied
            or self.allowed_values
            or self.reference is not None
        ):
            raise ValueError(f"{self.guard_type.value} does not accept declarative operands.")
        return self


class TransitionEffect(_FrozenStrictModel):
    """One ordered effect rendered into a K05 patch operation."""

    effect_type: EffectType
    path_template: str
    value_source: EffectValueSource | None = None
    literal_value: TransitionJsonValue | None = None

    @field_validator("path_template")
    @classmethod
    def _path_template_must_be_canonical(cls, value: str) -> str:
        if value != value.strip() or not value.startswith("/") or value == "/":
            raise ValueError("path_template must be an absolute canonical path.")
        if "\\" in value or "//" in value:
            raise ValueError("path_template cannot contain backslashes or empty segments.")
        for placeholder in _PLACEHOLDER_RE.findall(value):
            if placeholder not in _SUPPORTED_PLACEHOLDERS:
                raise ValueError(f"Unsupported path placeholder: {placeholder}.")
        for segment in value[1:].split("/"):
            if segment in _SUPPORTED_PLACEHOLDERS:
                continue
            if "{" in segment or "}" in segment or _TEMPLATE_SEGMENT_RE.fullmatch(segment) is None:
                raise ValueError("path_template contains a non-canonical segment.")
            if segment.startswith("_") or "__" in segment or segment in {".", ".."}:
                raise ValueError("path_template cannot contain private or traversal segments.")
        if any(segment in {"record_version", "updated_at"} for segment in value[1:].split("/")):
            raise ValueError("Effects cannot manipulate record_version or updated_at.")
        return value

    @model_validator(mode="after")
    def _value_source_must_match_effect(self) -> Self:
        literal_supplied = "literal_value" in self.model_fields_set
        if self.effect_type is EffectType.REMOVE_FIELD:
            has_remove_value = literal_supplied and self.literal_value is not None
            if self.value_source is not None or has_remove_value:
                raise ValueError("remove_field does not accept a value source.")
        elif self.value_source is None:
            raise ValueError(f"{self.effect_type.value} requires a value source.")
        elif self.value_source is EffectValueSource.LITERAL:
            if not literal_supplied:
                raise ValueError("literal value source requires literal_value.")
        elif literal_supplied and self.literal_value is not None:
            raise ValueError("literal_value is valid only for the literal value source.")
        return self


class TransitionDefinition(_FrozenStrictModel):
    """Versioned immutable declaration of one state transition."""

    transition_id: TransitionId
    name: str
    transition_key: str
    contract_version: SemanticVersion
    domain: TransitionDomain
    from_states: tuple[str, ...]
    to_state: str
    guards: tuple[TransitionGuard, ...] = ()
    effects: tuple[TransitionEffect, ...] = Field(min_length=1)
    priority: int = Field(default=100, ge=-10_000, le=10_000)
    allow_self_transition: bool = False
    description: str | None = None
    metadata: FrozenJsonObject = Field(default_factory=lambda: freeze_json_object({}))

    @field_validator("name")
    @classmethod
    def _name_must_not_be_blank(cls, value: str) -> str:
        return require_non_blank(value, field_name="name")

    @field_validator("description")
    @classmethod
    def _description_must_not_be_blank(cls, value: str | None) -> str | None:
        return None if value is None else require_non_blank(value, field_name="description")

    @field_validator("transition_key")
    @classmethod
    def _key_must_be_canonical(cls, value: str) -> str:
        if _TRANSITION_KEY_RE.fullmatch(value) is None:
            raise ValueError("transition_key must use canonical dotted lowercase grammar.")
        return value

    @field_validator("from_states")
    @classmethod
    def _source_states_must_be_non_empty_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(set(value)) != len(value):
            raise ValueError("from_states must be non-empty and unique.")
        return value

    @field_validator("metadata")
    @classmethod
    def _metadata_values_must_be_strings(cls, value: FrozenJsonObject) -> FrozenJsonObject:
        if any(not isinstance(item, str) for item in value.values()):
            raise ValueError("metadata values must be strings.")
        return value

    @model_validator(mode="after")
    def _definition_must_be_unambiguous(self) -> Self:
        if self.to_state in self.from_states and not self.allow_self_transition:
            raise ValueError("Self-transitions require allow_self_transition=True.")
        for field_name, values in (("guards", self.guards), ("effects", self.effects)):
            serialized = tuple(canonicalize_json(value.model_dump(mode="json")) for value in values)
            if len(set(serialized)) != len(serialized):
                raise ValueError(f"Duplicate canonical {field_name} are not allowed.")
        return self


class WorkflowTransitionDefinition(TransitionDefinition):
    """Transition bound to one exact generic workflow state space."""

    workflow_namespace: WorkflowNamespace
    workflow_definition_version: SemanticVersion
    workflow_definition_fingerprint: str

    @field_validator("workflow_definition_fingerprint")
    @classmethod
    def _workflow_fingerprint_must_be_canonical(cls, value: str) -> str:
        if SHA256_FINGERPRINT_RE.fullmatch(value) is None:
            raise ValueError(
                "workflow_definition_fingerprint must use sha256:<64 lowercase hex> format."
            )
        return value

    @model_validator(mode="after")
    def _domain_must_be_workflow_state(self) -> Self:
        if self.domain is not TransitionDomain.WORKFLOW_STATE:
            raise ValueError("WorkflowTransitionDefinition requires workflow_state domain.")
        return self


type AnyTransitionDefinition = TransitionDefinition | WorkflowTransitionDefinition


class TransitionRequest(_FrozenStrictModel):
    """Immutable request to resolve and evaluate one declared transition."""

    request_id: ChangeId | PatchId
    project_id: ProjectId
    target: TransitionTarget
    transition_id: TransitionId | None = None
    transition_key: str | None = None
    expected_from_state: str | None = None
    base_state_record_version: int | None = Field(default=None, ge=1)
    expected_state_content_fingerprint: str | None = None
    expected_target_record_version: int | None = Field(default=None, ge=1)
    expected_target_content_fingerprint: str | None = None
    requested_at: datetime
    metadata: FrozenJsonObject = Field(default_factory=lambda: freeze_json_object({}))

    @field_validator("transition_key", "expected_from_state")
    @classmethod
    def _optional_text_must_not_be_blank(cls, value: str | None, info: object) -> str | None:
        if value is None:
            return None
        return require_non_blank(value, field_name=getattr(info, "field_name", "request field"))

    @field_validator(
        "expected_state_content_fingerprint",
        "expected_target_content_fingerprint",
    )
    @classmethod
    def _fingerprints_must_be_canonical(cls, value: str | None) -> str | None:
        if value is not None and SHA256_FINGERPRINT_RE.fullmatch(value) is None:
            raise ValueError("Expected fingerprints must use sha256:<64 lowercase hex> format.")
        return value

    @field_validator("requested_at")
    @classmethod
    def _requested_at_must_be_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("metadata")
    @classmethod
    def _request_metadata_values_must_be_strings(cls, value: FrozenJsonObject) -> FrozenJsonObject:
        if any(not isinstance(item, str) for item in value.values()):
            raise ValueError("metadata values must be strings.")
        return value

    @model_validator(mode="after")
    def _exactly_one_selector_is_required(self) -> Self:
        if (self.transition_id is None) == (self.transition_key is None):
            raise ValueError("Exactly one of transition_id or transition_key is required.")
        return self


class GuardEvaluation(_FrozenStrictModel):
    """Structured outcome for one guard in declaration order."""

    guard: TransitionGuard
    passed: bool
    actual: TransitionJsonValue | None = None
    error: ErrorDetail | None = None

    @model_validator(mode="after")
    def _result_shape_must_match_status(self) -> Self:
        if self.passed == (self.error is not None):
            raise ValueError("A passing guard has no error; a failing guard requires one.")
        return self


class TransitionEvaluationResult(_FrozenStrictModel):
    """Complete deterministic transition evaluation outcome."""

    allowed: bool
    transition: AnyTransitionDefinition | None = None
    current_state: str | None = None
    target_state: str | None = None
    guard_evaluations: tuple[GuardEvaluation, ...] = ()
    state_patch: StatePatch | None = None
    dry_run_result: DryRunResult | None = None
    errors: tuple[ErrorDetail, ...] = ()

    @model_validator(mode="after")
    def _allowed_result_must_be_complete(self) -> Self:
        if self.allowed:
            if (
                self.transition is None
                or self.current_state is None
                or self.target_state is None
                or self.state_patch is None
                or self.dry_run_result is None
                or self.errors
            ):
                raise ValueError("Allowed transition results must expose every successful stage.")
        elif not self.errors:
            raise ValueError("Denied transition results require structured errors.")
        return self


__all__ = (
    "AnyTransitionDefinition",
    "EffectType",
    "EffectValueSource",
    "GuardEvaluation",
    "GuardType",
    "TransitionDefinition",
    "TransitionDomain",
    "TransitionEffect",
    "TransitionEvaluationResult",
    "TransitionGuard",
    "TransitionJsonValue",
    "TransitionRequest",
    "TransitionTarget",
    "WorkflowTransitionDefinition",
)
