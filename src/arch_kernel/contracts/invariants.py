"""Strict immutable contracts for WP-K07 invariant evaluation."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum, unique
from itertools import pairwise
from typing import Annotated, Any, Self

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
from arch_kernel.contracts.ids import InvariantId
from arch_kernel.contracts.project_state import ProjectState
from arch_kernel.contracts.references import TypedReference
from arch_kernel.contracts.versions import SemanticVersion
from arch_kernel.kernel.errors import ErrorDetail
from arch_kernel.kernel.event_validation import (
    FrozenJsonObject,
    FrozenJsonValue,
    freeze_json_object,
    freeze_json_value,
    thaw_json,
)
from arch_kernel.kernel.time import ensure_utc

_INVARIANT_KEY_RE = re.compile(
    r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_]*){2,}$",
    re.ASCII,
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

type InvariantJsonValue = Annotated[
    FrozenJsonValue,
    BeforeValidator(freeze_json_value),
    PlainSerializer(thaw_json, when_used="json"),
    WithJsonSchema(_JSON_SCHEMA),
]


@unique
class InvariantSeverity(StrEnum):
    """Policy severity, independent from diagnostic transport severity."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@unique
class InvariantScope(StrEnum):
    """Closed scopes available for deterministic invariant selection."""

    PROJECT = "project"
    LIFECYCLE = "lifecycle"
    PHASE = "phase"
    ARTIFACT = "artifact"
    REQUIREMENT = "requirement"
    RISK = "risk"
    DEPENDENCY = "dependency"
    HISTORY = "history"


@unique
class InvariantKind(StrEnum):
    """Closed canonical implementations supported by the K07 engine."""

    SINGLE_ACTIVE_PHASE = "single_active_phase"
    LIFECYCLE_PHASE_ALIGNMENT = "lifecycle_phase_alignment"
    APPROVED_BASELINE_INTEGRITY = "approved_baseline_integrity"
    REQUIRED_DEPENDENCY_SATISFACTION = "required_dependency_satisfaction"
    REQUIREMENT_TRACEABILITY = "requirement_traceability"
    CRITICAL_RISK_CONTROL = "critical_risk_control"
    TERMINAL_PHASE_CONSISTENCY = "terminal_phase_consistency"
    IMMUTABLE_HISTORY_CONSISTENCY = "immutable_history_consistency"
    MONOTONIC_RECORD_VERSIONS = "monotonic_record_versions"


class _FrozenStrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class InvariantDefinition(_FrozenStrictModel):
    """Immutable declaration that selects one closed invariant evaluator."""

    invariant_id: InvariantId
    key: str
    title: str
    description: str
    kind: InvariantKind
    scope: InvariantScope
    severity: InvariantSeverity
    enabled: bool = True
    blocking: bool
    priority: int = Field(ge=-10_000, le=10_000)
    configuration: FrozenJsonObject = Field(default_factory=lambda: freeze_json_object({}))
    remediation_hint: str | None = None
    contract_version: SemanticVersion
    schema_uri: str

    @field_validator("key")
    @classmethod
    def _key_must_be_canonical(cls, value: str) -> str:
        if _INVARIANT_KEY_RE.fullmatch(value) is None:
            raise ValueError("key must use at least three canonical lowercase dotted segments.")
        return value

    @field_validator("title", "description", "schema_uri")
    @classmethod
    def _required_text_must_not_be_blank(cls, value: str, info: object) -> str:
        return require_non_blank(value, field_name=getattr(info, "field_name", "text"))

    @field_validator("remediation_hint")
    @classmethod
    def _remediation_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_non_blank(value, field_name="remediation_hint")


class InvariantEvidence(_FrozenStrictModel):
    """Stable evidence attached to one invariant violation."""

    reference: TypedReference | None = None
    path: str | None = None
    observed: InvariantJsonValue | None = None
    expected: InvariantJsonValue | None = None
    message: str | None = None

    @field_validator("path")
    @classmethod
    def _path_must_be_canonical(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value != value.strip() or not value.startswith("/"):
            raise ValueError("Evidence paths must be absolute canonical paths.")
        return value

    @field_validator("message")
    @classmethod
    def _message_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_non_blank(value, field_name="message")


class InvariantViolation(_FrozenStrictModel):
    """One independently consumable invariant finding."""

    invariant_id: InvariantId
    key: str
    kind: InvariantKind
    scope: InvariantScope
    severity: InvariantSeverity
    blocking: bool
    message: str
    evidence: tuple[InvariantEvidence, ...] = Field(min_length=1)
    remediation_hint: str | None = None

    @field_validator("key", "message")
    @classmethod
    def _violation_text_must_not_be_blank(cls, value: str, info: object) -> str:
        return require_non_blank(value, field_name=getattr(info, "field_name", "text"))


def _copy_context_inputs(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    copied = dict(value)
    state = copied.get("state")
    if isinstance(state, ProjectState):
        copied["state"] = state.model_copy(deep=True)
    elif isinstance(state, Mapping):
        copied["state"] = ProjectState.model_validate_json(json.dumps(state))
    else:
        raise TypeError("state must be a ProjectState or its JSON object representation.")
    history = copied.get("history")
    if isinstance(history, (list, tuple)):
        copied["history"] = tuple(
            item.model_copy(deep=True)
            if isinstance(item, EventEnvelope)
            else EventEnvelope.model_validate_json(json.dumps(item))
            for item in history
        )
    snapshots = copied.get("previous_snapshots")
    if isinstance(snapshots, (list, tuple)):
        copied["previous_snapshots"] = tuple(
            item.model_copy(deep=True)
            if isinstance(item, ProjectState)
            else ProjectState.model_validate_json(json.dumps(item))
            for item in snapshots
        )
    for field_name in ("selected_keys", "selected_scopes"):
        selected = copied.get(field_name)
        if isinstance(selected, list):
            copied[field_name] = tuple(selected)
    selected_scopes = copied.get("selected_scopes")
    if isinstance(selected_scopes, tuple):
        copied["selected_scopes"] = tuple(
            InvariantScope(item) if isinstance(item, str) else item for item in selected_scopes
        )
    return copied


class InvariantEvaluationContext(_FrozenStrictModel):
    """Detached current-state and optional historical invariant inputs."""

    state: SkipValidation[ProjectState]
    evaluated_at: datetime
    history: tuple[SkipValidation[EventEnvelope], ...] = ()
    previous_snapshots: tuple[SkipValidation[ProjectState], ...] = ()
    selected_keys: tuple[str, ...] | None = None
    selected_scopes: tuple[InvariantScope, ...] | None = None

    @model_validator(mode="before")
    @classmethod
    def _inputs_must_be_copied_defensively(cls, value: Any) -> Any:
        return _copy_context_inputs(value)

    @field_validator("evaluated_at")
    @classmethod
    def _evaluated_at_must_be_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("history")
    @classmethod
    def _history_must_use_canonical_order(
        cls, value: tuple[EventEnvelope, ...]
    ) -> tuple[EventEnvelope, ...]:
        return tuple(
            sorted(
                value,
                key=lambda event: (
                    event.occurred_at,
                    event.recorded_at,
                    str(event.event_id),
                ),
            )
        )

    @field_validator("previous_snapshots")
    @classmethod
    def _snapshots_must_be_oldest_to_newest(
        cls, value: tuple[ProjectState, ...]
    ) -> tuple[ProjectState, ...]:
        state_versions = tuple(snapshot.state_version_updated for snapshot in value)
        if any(later < earlier for earlier, later in pairwise(state_versions)):
            raise ValueError(
                "previous_snapshots must be ordered oldest-to-newest by state_version_updated."
            )
        return value

    @field_validator("selected_keys")
    @classmethod
    def _selected_keys_must_be_unique(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is None:
            return None
        for key in value:
            require_non_blank(key, field_name="selected_keys")
        require_unique(value, field_name="selected_keys")
        return tuple(sorted(value))

    @field_validator("selected_scopes")
    @classmethod
    def _selected_scopes_must_be_unique(
        cls, value: tuple[InvariantScope, ...] | None
    ) -> tuple[InvariantScope, ...] | None:
        if value is None:
            return None
        require_unique(value, field_name="selected_scopes")
        return tuple(sorted(value, key=str))


class InvariantEvaluationResult(_FrozenStrictModel):
    """Deterministic accumulated result for one invariant evaluation."""

    success: bool
    blocking_failure: bool
    evaluated_invariant_ids: tuple[InvariantId, ...]
    skipped_invariant_ids: tuple[InvariantId, ...]
    violations: tuple[InvariantViolation, ...]
    counts_by_severity: FrozenJsonObject
    evaluated_at: datetime
    input_fingerprint: str
    errors: tuple[ErrorDetail, ...] = ()

    @field_validator("evaluated_at")
    @classmethod
    def _result_time_must_be_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("input_fingerprint")
    @classmethod
    def _input_fingerprint_must_be_canonical(cls, value: str) -> str:
        if SHA256_FINGERPRINT_RE.fullmatch(value) is None:
            raise ValueError("input_fingerprint must use sha256:<64 lowercase hex> format.")
        return value

    @model_validator(mode="after")
    def _status_and_counts_must_match_violations(self) -> Self:
        has_blocking = any(violation.blocking for violation in self.violations)
        if self.blocking_failure != has_blocking or self.success == has_blocking:
            raise ValueError("success and blocking_failure must match blocking violations.")
        expected_counts = {
            severity.value: sum(violation.severity is severity for violation in self.violations)
            for severity in InvariantSeverity
        }
        if thaw_json(self.counts_by_severity) != expected_counts:
            raise ValueError("counts_by_severity must match the violation tuple.")
        return self


__all__ = (
    "InvariantDefinition",
    "InvariantEvaluationContext",
    "InvariantEvaluationResult",
    "InvariantEvidence",
    "InvariantJsonValue",
    "InvariantKind",
    "InvariantScope",
    "InvariantSeverity",
    "InvariantViolation",
)
