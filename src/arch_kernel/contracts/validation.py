"""Strict contracts for the WP-K08 unified validation pipeline."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum, unique
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    SkipValidation,
    WithJsonSchema,
    field_validator,
    model_validator,
)
from pydantic.json_schema import JsonSchemaValue

from arch_kernel.contracts._validation import (
    SHA256_FINGERPRINT_RE,
    require_non_blank,
    require_unique,
)
from arch_kernel.contracts.events import EventEnvelope
from arch_kernel.contracts.invariants import InvariantScope
from arch_kernel.contracts.patches import StatePatch
from arch_kernel.contracts.project_state import ProjectState
from arch_kernel.contracts.transitions import TransitionRequest
from arch_kernel.kernel.errors import Severity
from arch_kernel.kernel.event_validation import (
    FrozenJsonObject,
    FrozenJsonValue,
    freeze_json_value,
    thaw_json,
)
from arch_kernel.kernel.time import ensure_utc

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

type ValidationJsonValue = Annotated[
    FrozenJsonValue,
    BeforeValidator(freeze_json_value),
    PlainSerializer(thaw_json, when_used="json"),
    WithJsonSchema(_JSON_SCHEMA),
]


@unique
class ValidationStage(StrEnum):
    CONTRACT = "contract"
    AGGREGATE = "aggregate"
    PATCH = "patch"
    TRANSITION = "transition"
    INVARIANT = "invariant"
    FINALIZATION = "finalization"


@unique
class ValidationIntent(StrEnum):
    VALIDATE_STATE = "validate_state"
    VALIDATE_PATCH = "validate_patch"
    VALIDATE_TRANSITION = "validate_transition"
    VALIDATE_RELEASE = "validate_release"
    VALIDATE_HISTORY = "validate_history"


@unique
class ValidationDisposition(StrEnum):
    ACCEPTED = "accepted"
    ACCEPTED_WITH_FINDINGS = "accepted_with_findings"
    REJECTED = "rejected"
    INVALID_INPUT = "invalid_input"
    NOT_EVALUATED = "not_evaluated"


@unique
class ValidationFindingKind(StrEnum):
    CONTRACT_ERROR = "contract_error"
    AGGREGATE_ERROR = "aggregate_error"
    PATCH_ERROR = "patch_error"
    TRANSITION_ERROR = "transition_error"
    GUARD_FAILURE = "guard_failure"
    INVARIANT_VIOLATION = "invariant_violation"
    PIPELINE_ERROR = "pipeline_error"


@unique
class InvariantEvaluationTarget(StrEnum):
    ORIGINAL = "original"
    PROJECTED = "projected"
    BOTH = "both"


class _FrozenStrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ValidationFinding(_FrozenStrictModel):
    kind: ValidationFindingKind
    stage: ValidationStage
    code: str
    message: str
    severity: Severity
    blocking: bool
    sequence: int = Field(ge=1)
    path: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    expected: ValidationJsonValue | None = None
    actual: ValidationJsonValue | None = None
    remediation_hint: str | None = None
    source_id: str | None = None
    source_key: str | None = None
    source_target: InvariantEvaluationTarget | None = None

    @field_validator(
        "code",
        "message",
        "path",
        "entity_type",
        "entity_id",
        "remediation_hint",
        "source_id",
        "source_key",
    )
    @classmethod
    def _text_must_not_be_blank(cls, value: str | None, info: object) -> str | None:
        if value is None:
            return None
        return require_non_blank(value, field_name=getattr(info, "field_name", "finding field"))


class ValidationStageResult(_FrozenStrictModel):
    stage: ValidationStage
    executed: bool
    success: bool
    blocking_failure: bool
    findings: tuple[ValidationFinding, ...] = ()
    metadata: FrozenJsonObject
    input_fingerprint: str | None = None
    output_fingerprint: str | None = None

    @field_validator("input_fingerprint", "output_fingerprint")
    @classmethod
    def _fingerprints_must_be_canonical(cls, value: str | None) -> str | None:
        if value is not None and SHA256_FINGERPRINT_RE.fullmatch(value) is None:
            raise ValueError("Stage fingerprints must use sha256:<64 lowercase hex> format.")
        return value

    @model_validator(mode="after")
    def _status_must_match_findings(self) -> Self:
        has_blocking = any(finding.blocking for finding in self.findings)
        if self.blocking_failure != has_blocking:
            raise ValueError("blocking_failure must match blocking findings.")
        if self.success == has_blocking:
            raise ValueError("success must be true exactly when no blocking finding exists.")
        if not self.executed and self.findings:
            raise ValueError("Skipped stages cannot contain findings.")
        return self


class ValidationPipelinePolicy(_FrozenStrictModel):
    continue_after_blocking_failure: bool = False
    invariant_target: InvariantEvaluationTarget | None = None
    non_blocking_findings_affect_disposition: bool = True
    enabled_stages: tuple[ValidationStage, ...] | None = None
    selected_invariant_keys: tuple[str, ...] | None = None
    selected_invariant_scopes: tuple[InvariantScope, ...] | None = None
    expose_transition_outputs: bool = True
    prevent_projected_invariants_after_failed_projection: bool = True

    @field_validator("enabled_stages")
    @classmethod
    def _stages_must_be_unique(
        cls, value: tuple[ValidationStage, ...] | None
    ) -> tuple[ValidationStage, ...] | None:
        if value is None:
            return None
        require_unique(value, field_name="enabled_stages")
        return value

    @field_validator("selected_invariant_keys")
    @classmethod
    def _keys_must_be_unique(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is None:
            return None
        for key in value:
            require_non_blank(key, field_name="selected_invariant_keys")
        require_unique(value, field_name="selected_invariant_keys")
        return tuple(sorted(value))

    @field_validator("selected_invariant_scopes")
    @classmethod
    def _scopes_must_be_unique(
        cls, value: tuple[InvariantScope, ...] | None
    ) -> tuple[InvariantScope, ...] | None:
        if value is None:
            return None
        require_unique(value, field_name="selected_invariant_scopes")
        return tuple(sorted(value, key=str))


class ValidationPipelineRequest(_FrozenStrictModel):
    intent: ValidationIntent
    evaluated_at: datetime
    state: SkipValidation[ProjectState] | None = None
    raw_state: FrozenJsonObject | None = None
    patch: SkipValidation[StatePatch] | None = None
    raw_patch: FrozenJsonObject | None = None
    transition_request: TransitionRequest | None = None
    event_history: tuple[EventEnvelope, ...] = ()
    previous_snapshots: tuple[ProjectState, ...] = ()
    selected_invariant_keys: tuple[str, ...] | None = None
    selected_invariant_scopes: tuple[InvariantScope, ...] | None = None
    policy: ValidationPipelinePolicy = Field(default_factory=ValidationPipelinePolicy)
    expected_input_fingerprint: str | None = None

    @field_validator("evaluated_at")
    @classmethod
    def _evaluated_at_must_be_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("expected_input_fingerprint")
    @classmethod
    def _expected_fingerprint_must_be_canonical(cls, value: str | None) -> str | None:
        if value is not None and SHA256_FINGERPRINT_RE.fullmatch(value) is None:
            raise ValueError(
                "expected_input_fingerprint must use sha256:<64 lowercase hex> format."
            )
        return value

    @field_validator("selected_invariant_keys")
    @classmethod
    def _selected_keys_must_be_unique(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is None:
            return None
        require_unique(value, field_name="selected_invariant_keys")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def _intent_shape_must_be_unambiguous(self) -> Self:
        has_state = self.state is not None or self.raw_state is not None
        has_patch = self.patch is not None or self.raw_patch is not None
        if not has_state:
            raise ValueError("Every validation intent requires state or raw_state.")
        if self.intent is ValidationIntent.VALIDATE_PATCH:
            if not has_patch or self.transition_request is not None:
                raise ValueError("validate_patch requires a patch and forbids transition_request.")
        elif self.intent is ValidationIntent.VALIDATE_TRANSITION:
            if self.transition_request is None or has_patch:
                raise ValueError(
                    "validate_transition requires transition_request and forbids supplied patches."
                )
        elif has_patch or self.transition_request is not None:
            raise ValueError("This validation intent does not accept patches or transitions.")
        if self.intent is not ValidationIntent.VALIDATE_HISTORY and (
            self.event_history or self.previous_snapshots
        ):
            raise ValueError("History and snapshots are reserved for validate_history.")
        return self


class ValidationPipelineResult(_FrozenStrictModel):
    intent: ValidationIntent
    disposition: ValidationDisposition
    success: bool
    blocking_failure: bool
    contract_stage: ValidationStageResult
    aggregate_stage: ValidationStageResult
    patch_stage: ValidationStageResult
    transition_stage: ValidationStageResult
    invariant_stage: ValidationStageResult
    finalization_stage: ValidationStageResult
    findings: tuple[ValidationFinding, ...]
    counts_by_stage: FrozenJsonObject
    counts_by_severity: FrozenJsonObject
    counts_by_kind: FrozenJsonObject
    evaluated_at: datetime
    validated_state: ProjectState | None = None
    generated_patch: StatePatch | None = None
    projected_state: ProjectState | None = None
    transition_summary: FrozenJsonObject | None = None
    invariant_summary: FrozenJsonObject | None = None
    input_fingerprint: str
    result_fingerprint: str

    @field_validator("evaluated_at")
    @classmethod
    def _result_time_must_be_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("input_fingerprint", "result_fingerprint")
    @classmethod
    def _result_fingerprints_must_be_canonical(cls, value: str) -> str:
        if SHA256_FINGERPRINT_RE.fullmatch(value) is None:
            raise ValueError("Pipeline fingerprints must use sha256:<64 lowercase hex> format.")
        return value

    @model_validator(mode="after")
    def _result_must_be_internally_consistent(self) -> Self:
        stages = (
            self.contract_stage,
            self.aggregate_stage,
            self.patch_stage,
            self.transition_stage,
            self.invariant_stage,
            self.finalization_stage,
        )
        expected = tuple(ValidationStage)
        if tuple(stage.stage for stage in stages) != expected:
            raise ValueError("Pipeline stages must use canonical order.")
        if self.findings != tuple(finding for stage in stages for finding in stage.findings):
            raise ValueError("Flat findings must preserve stage and finding order.")
        has_blocking = any(finding.blocking for finding in self.findings)
        if self.blocking_failure != has_blocking or self.success == has_blocking:
            raise ValueError("Pipeline success must match blocking findings.")
        if tuple(finding.sequence for finding in self.findings) != tuple(
            range(1, len(self.findings) + 1)
        ):
            raise ValueError("Finding sequence must be contiguous and one-based.")
        return self


__all__ = (
    "InvariantEvaluationTarget",
    "ValidationDisposition",
    "ValidationFinding",
    "ValidationFindingKind",
    "ValidationIntent",
    "ValidationJsonValue",
    "ValidationPipelinePolicy",
    "ValidationPipelineRequest",
    "ValidationPipelineResult",
    "ValidationStage",
    "ValidationStageResult",
)
