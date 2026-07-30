"""Pure validation helpers for immutable event envelopes."""

from __future__ import annotations

import math
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Self, cast

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

from arch_kernel.kernel.errors import ErrorCode, EventValidationError

if TYPE_CHECKING:
    from arch_kernel.contracts.ids import EventId

type JsonScalarValue = None | bool | int | float | str
type JsonValue = JsonScalarValue | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

_EVENT_TYPE_RE = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_]+){2,}$", re.ASCII)
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._:/-]+$", re.ASCII)


@dataclass(frozen=True, slots=True, eq=False)
class FrozenJsonObject(Mapping[str, "FrozenJsonValue"]):
    """Recursively immutable JSON object with explicit Pydantic serialization."""

    _items: tuple[tuple[str, FrozenJsonValue], ...]

    def __getitem__(self, key: str) -> FrozenJsonValue:
        for item_key, value in self._items:
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return f"FrozenJsonObject({dict(self.items())!r})"

    def __hash__(self) -> int:
        return hash(frozenset(self._items))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FrozenJsonObject):
            return dict(self.items()) == dict(other.items())
        if isinstance(other, Mapping):
            try:
                return self == freeze_json_object(dict(other.items()))
            except EventValidationError:
                return False
        return False

    @classmethod
    def _validate(cls, value: object) -> Self:
        frozen = freeze_json_object(value)
        if not isinstance(frozen, cls):  # pragma: no cover - guaranteed by helper
            raise AssertionError("JSON object freezing returned an unexpected type.")
        return frozen

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_plain_validator_function(
            cls._validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                thaw_json,
                when_used="json",
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        _core_schema: core_schema.CoreSchema,
        _handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        return {
            "type": "object",
            "title": cls.__name__,
            "additionalProperties": {
                "anyOf": [
                    {"type": "null"},
                    {"type": "boolean"},
                    {"type": "integer"},
                    {"type": "number"},
                    {"type": "string"},
                    {"type": "array"},
                    {"type": "object"},
                ]
            },
        }


type FrozenJsonValue = JsonScalarValue | tuple[FrozenJsonValue, ...] | FrozenJsonObject


def validate_event_type(value: str) -> str:
    """Validate and preserve a canonical dotted event type."""

    if not isinstance(value, str):
        raise EventValidationError(
            "Event type must be a string.",
            code=ErrorCode.INVALID_EVENT_TYPE,
            path=("event_type",),
            expected="<domain>.<entity>.<action>",
            actual=type(value).__name__,
            remediation_hint="Use lowercase ASCII segments separated by single dots.",
        )
    if len(value) > 160 or _EVENT_TYPE_RE.fullmatch(value) is None:
        raise EventValidationError(
            "Event type must contain at least three canonical lowercase ASCII segments.",
            code=ErrorCode.INVALID_EVENT_TYPE,
            path=("event_type",),
            expected="<domain>.<entity>.<action>, maximum 160 characters",
            actual=value,
            remediation_hint="Use only a-z, 0-9, and underscore inside each segment.",
        )
    return value


def validate_idempotency_key(value: str) -> str:
    """Validate and preserve an event idempotency key."""

    if not isinstance(value, str):
        raise EventValidationError(
            "Idempotency key must be a string.",
            code=ErrorCode.INVALID_IDEMPOTENCY_KEY,
            path=("idempotency_key",),
            expected="8 to 200 safe ASCII characters",
            actual=type(value).__name__,
        )
    if not 8 <= len(value) <= 200 or _IDEMPOTENCY_KEY_RE.fullmatch(value) is None:
        raise EventValidationError(
            "Idempotency key must contain 8 to 200 safe ASCII characters.",
            code=ErrorCode.INVALID_IDEMPOTENCY_KEY,
            path=("idempotency_key",),
            expected="A-Z, a-z, 0-9, dot, underscore, colon, slash, or hyphen",
            actual=value,
            remediation_hint="Remove whitespace and unsafe characters without changing key casing.",
        )
    return value


def _copy_json_value(value: object, *, path: tuple[str | int, ...]) -> JsonValue:
    if value is None or type(value) in (bool, int, str):
        return cast(JsonScalarValue, value)
    if type(value) is float:
        if math.isfinite(value):
            return value
        raise EventValidationError(
            "Event payload numbers must be finite.",
            code=ErrorCode.INVALID_EVENT_PAYLOAD,
            path=path,
            expected="finite JSON number",
            actual=str(value),
            remediation_hint="Replace NaN or Infinity with a finite number or null.",
        )
    if type(value) is list:
        return [_copy_json_value(item, path=(*path, index)) for index, item in enumerate(value)]
    if type(value) is dict:
        copied: JsonObject = {}
        for key, item in value.items():
            if type(key) is not str:
                raise EventValidationError(
                    "Event payload object keys must be strings.",
                    code=ErrorCode.INVALID_EVENT_PAYLOAD,
                    path=path,
                    expected="string object key",
                    actual=type(key).__name__,
                    remediation_hint="Encode every payload object key as a string.",
                )
            copied[key] = _copy_json_value(item, path=(*path, key))
        return copied
    raise EventValidationError(
        "Event payload contains a value outside the JSON data model.",
        code=ErrorCode.INVALID_EVENT_PAYLOAD,
        path=path,
        expected="null, boolean, integer, finite float, string, array, or object",
        actual=type(value).__name__,
        remediation_hint="Convert the value explicitly to a JSON-compatible representation.",
    )


def validate_json_object(value: object) -> JsonObject:
    """Validate a strict JSON object and return a recursive defensive copy."""

    if type(value) is not dict:
        raise EventValidationError(
            "Event payload root must be a JSON object.",
            code=ErrorCode.INVALID_EVENT_PAYLOAD,
            path=("payload",),
            expected="dict[str, JsonValue]",
            actual=type(value).__name__,
            remediation_hint="Wrap the payload fields in a JSON object.",
        )
    copied = _copy_json_value(value, path=("payload",))
    if not isinstance(copied, dict):  # pragma: no cover - guarded by the root check
        raise AssertionError("JSON object validation returned a non-object.")
    return copied


def validate_json_value(value: object) -> JsonValue:
    """Validate one strict JSON value and return a recursive defensive copy."""

    return _copy_json_value(value, path=("value",))


def _freeze_validated_json(value: JsonValue) -> FrozenJsonValue:
    if isinstance(value, dict):
        return FrozenJsonObject(
            tuple((key, _freeze_validated_json(item)) for key, item in value.items())
        )
    if isinstance(value, list):
        return tuple(_freeze_validated_json(item) for item in value)
    return value


def freeze_json_object(value: object) -> FrozenJsonObject:
    """Validate and recursively freeze one JSON object."""

    if isinstance(value, FrozenJsonObject):
        return value
    frozen = _freeze_validated_json(validate_json_object(value))
    if not isinstance(frozen, FrozenJsonObject):  # pragma: no cover - root is validated
        raise AssertionError("JSON object freezing returned a non-object.")
    return frozen


def freeze_json_value(value: object) -> FrozenJsonValue:
    """Validate and recursively freeze one JSON value."""

    if isinstance(value, FrozenJsonObject):
        return value
    return _freeze_validated_json(validate_json_value(value))


def thaw_json(value: FrozenJsonValue) -> JsonValue:
    """Convert frozen JSON containers back to conventional JSON containers."""

    if isinstance(value, FrozenJsonObject):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def validate_event_temporal_order(occurred_at: datetime, recorded_at: datetime) -> None:
    """Reject an event recorded before it occurred."""

    if recorded_at < occurred_at:
        raise EventValidationError(
            "recorded_at must be greater than or equal to occurred_at.",
            code=ErrorCode.INVALID_EVENT_TIMESTAMP_ORDER,
            path=("recorded_at",),
            expected="recorded_at >= occurred_at",
            actual=recorded_at.isoformat(),
            remediation_hint="Preserve the fact timestamp and use a later registration timestamp.",
        )


def validate_event_causality(
    event_id: EventId,
    correlation_id: EventId | None,
    causation_id: EventId | None,
) -> None:
    """Validate local causal and correlation references."""

    if correlation_id == event_id:
        raise EventValidationError(
            "correlation_id cannot reference the event itself.",
            code=ErrorCode.INVALID_CAUSAL_REFERENCE,
            path=("correlation_id",),
            entity_id=str(event_id),
            expected="another EventId or null",
            actual=str(correlation_id),
        )
    if causation_id == event_id:
        raise EventValidationError(
            "causation_id cannot reference the event itself.",
            code=ErrorCode.INVALID_CAUSAL_REFERENCE,
            path=("causation_id",),
            entity_id=str(event_id),
            expected="another EventId or null",
            actual=str(causation_id),
        )
    if causation_id is not None and correlation_id is None:
        raise EventValidationError(
            "causation_id requires correlation_id.",
            code=ErrorCode.INVALID_CAUSAL_REFERENCE,
            path=("correlation_id",),
            entity_id=str(event_id),
            expected="EventId when causation_id is present",
            actual="null",
            remediation_hint="Supply the event chain correlation ID.",
        )


__all__ = (
    "FrozenJsonObject",
    "FrozenJsonValue",
    "JsonObject",
    "JsonValue",
    "freeze_json_object",
    "freeze_json_value",
    "thaw_json",
    "validate_event_causality",
    "validate_event_temporal_order",
    "validate_event_type",
    "validate_idempotency_key",
    "validate_json_object",
    "validate_json_value",
)
