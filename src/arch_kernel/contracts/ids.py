"""Canonical typed identifiers for ARch contracts."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from types import NotImplementedType
from typing import Any, ClassVar, Self

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

from arch_kernel.kernel.errors import IdentifierValidationError

CROCKFORD_BASE32_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ULID_LENGTH = 26
_ULID_RANDOMNESS_BITS = 80
_ULID_TIMESTAMP_BITS = 48
_ULID_VALUE_BITS = 128
_ULID_CHAR_TO_VALUE = {char: index for index, char in enumerate(CROCKFORD_BASE32_ALPHABET)}


def _encode_ulid(value: int) -> str:
    chars: list[str] = []
    remaining = value
    for _ in range(ULID_LENGTH):
        chars.append(CROCKFORD_BASE32_ALPHABET[remaining & 0b11111])
        remaining >>= 5
    return "".join(reversed(chars))


def _decode_ulid(value: str) -> int:
    decoded = 0
    for char in value:
        decoded = (decoded << 5) | _ULID_CHAR_TO_VALUE[char]
    return decoded


def _generate_ulid_component() -> str:
    timestamp_ms = time.time_ns() // 1_000_000
    if timestamp_ms >= 1 << _ULID_TIMESTAMP_BITS:
        raise OverflowError("Current timestamp exceeds the 48-bit ULID timestamp range.")
    randomness = secrets.randbits(_ULID_RANDOMNESS_BITS)
    return _encode_ulid((timestamp_ms << _ULID_RANDOMNESS_BITS) | randomness)


def _validate_ulid_component(value: str) -> str:
    if len(value) != ULID_LENGTH:
        raise IdentifierValidationError(
            "ULID component must contain exactly 26 characters.",
            expected=ULID_LENGTH,
            actual=len(value),
            remediation_hint="Use a canonical 26-character Crockford Base32 ULID.",
        )

    for char in value:
        if char not in _ULID_CHAR_TO_VALUE:
            raise IdentifierValidationError(
                "ULID component contains a character outside Crockford Base32.",
                expected="Crockford Base32 uppercase characters without I, L, O, or U",
                actual=char,
                remediation_hint="Use uppercase canonical ULID text.",
            )

    decoded = _decode_ulid(value)
    if decoded >= 1 << _ULID_VALUE_BITS:
        raise IdentifierValidationError(
            "ULID component exceeds the 128-bit ULID range.",
            expected="ULID value below 2^128",
            actual=value,
        )

    return value


@dataclass(frozen=True, slots=True, init=False)
class CanonicalId:
    """Base value object for prefixed canonical IDs."""

    _value: str = field(repr=False)

    prefix: ClassVar[str] = ""
    target_type: ClassVar[str] = ""

    def __init__(self, value: str) -> None:
        object.__setattr__(self, "_value", self._validate(value))

    @classmethod
    def _validate(cls, value: object) -> str:
        cls._assert_configured()

        if not isinstance(value, str):
            raise IdentifierValidationError(
                "Canonical IDs must be parsed from strings.",
                expected="string",
                actual=type(value).__name__,
            )
        if value == "":
            raise IdentifierValidationError(
                "Canonical ID cannot be empty.",
                expected=f"{cls.prefix}-<ULID>",
                actual=value,
            )
        if "-" not in value:
            raise IdentifierValidationError(
                "Canonical ID must contain a '-' separator.",
                expected=f"{cls.prefix}-<ULID>",
                actual=value,
            )

        prefix, ulid_component = value.split("-", 1)
        if prefix != cls.prefix:
            raise IdentifierValidationError(
                "Canonical ID prefix does not match the expected type.",
                entity_type=cls.target_type,
                expected=cls.prefix,
                actual=prefix,
            )
        _validate_ulid_component(ulid_component)
        return f"{cls.prefix}-{ulid_component}"

    @classmethod
    def _assert_configured(cls) -> None:
        if not cls.prefix or not cls.target_type:
            raise TypeError("CanonicalId subclasses must define prefix and target_type.")

    @classmethod
    def generate(cls) -> Self:
        """Generate a new ID with this type's fixed prefix."""

        return cls.from_str(f"{cls.prefix}-{_generate_ulid_component()}")

    @classmethod
    def from_str(cls, value: str) -> Self:
        """Parse and validate a canonical ID string."""

        return cls(value)

    @property
    def ulid(self) -> str:
        """Return the validated ULID component without the type prefix."""

        return self._value.split("-", 1)[1]

    def __str__(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._value!r})"

    def __eq__(self, other: object) -> bool:
        if self.__class__ is not other.__class__:
            return False
        return self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __lt__(self, other: object) -> bool | NotImplementedType:
        if not isinstance(other, CanonicalId) or self.__class__ is not other.__class__:
            return NotImplemented
        return self._value < other._value

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        from_string_schema = core_schema.no_info_after_validator_function(
            cls.from_str,
            core_schema.str_schema(),
        )
        return core_schema.json_or_python_schema(
            json_schema=from_string_schema,
            python_schema=core_schema.union_schema(
                [
                    core_schema.is_instance_schema(cls),
                    from_string_schema,
                ]
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
            "pattern": f"^{cls.prefix}-[{CROCKFORD_BASE32_ALPHABET}]{{{ULID_LENGTH}}}$",
            "examples": [f"{cls.prefix}-01HZX7M3FQ1T2Q9V8Y6K4C2B1A"],
        }


class ProjectId(CanonicalId):
    prefix = "PRJ"
    target_type = "project"


class PhaseExecutionId(CanonicalId):
    prefix = "PHX"
    target_type = "phase_execution"


class PhaseId(CanonicalId):
    """Canonical identifier for a defined ARch phase."""

    prefix = "PHS"
    target_type = "phase"


class ArtifactId(CanonicalId):
    prefix = "ART"
    target_type = "artifact"


class RequirementId(CanonicalId):
    prefix = "REQ"
    target_type = "requirement"


class GateId(CanonicalId):
    prefix = "GATE"
    target_type = "gate"


class GateExecutionId(CanonicalId):
    prefix = "GEX"
    target_type = "gate_execution"


class ApprovalId(CanonicalId):
    prefix = "APR"
    target_type = "approval"


class ChangeId(CanonicalId):
    prefix = "CHG"
    target_type = "change"


class EventId(CanonicalId):
    prefix = "EVT"
    target_type = "event"


class AssignmentId(CanonicalId):
    prefix = "ASN"
    target_type = "assignment"


class PatchId(CanonicalId):
    prefix = "PATCH"
    target_type = "patch"


class DecisionId(CanonicalId):
    prefix = "DEC"
    target_type = "decision"


class RiskId(CanonicalId):
    prefix = "RISK"
    target_type = "risk"


class TransitionId(CanonicalId):
    prefix = "TRN"
    target_type = "transition"


class InvariantId(CanonicalId):
    prefix = "INV"
    target_type = "invariant"


class MigrationId(CanonicalId):
    prefix = "MIG"
    target_type = "migration"


CANONICAL_ID_TYPES: tuple[type[CanonicalId], ...] = (
    ProjectId,
    PhaseExecutionId,
    PhaseId,
    ArtifactId,
    RequirementId,
    GateId,
    GateExecutionId,
    ApprovalId,
    ChangeId,
    EventId,
    AssignmentId,
    PatchId,
    DecisionId,
    RiskId,
    TransitionId,
    InvariantId,
    MigrationId,
)

type AnyCanonicalId = (
    ProjectId
    | PhaseExecutionId
    | PhaseId
    | ArtifactId
    | RequirementId
    | GateId
    | GateExecutionId
    | ApprovalId
    | ChangeId
    | EventId
    | AssignmentId
    | PatchId
    | DecisionId
    | RiskId
    | TransitionId
    | InvariantId
    | MigrationId
)


def target_type_for_id(value: CanonicalId) -> str:
    """Return the canonical reference target type for an ID instance."""

    return value.target_type


__all__ = (
    "CANONICAL_ID_TYPES",
    "AnyCanonicalId",
    "ApprovalId",
    "ArtifactId",
    "AssignmentId",
    "CanonicalId",
    "ChangeId",
    "DecisionId",
    "EventId",
    "GateExecutionId",
    "GateId",
    "InvariantId",
    "MigrationId",
    "PatchId",
    "PhaseExecutionId",
    "PhaseId",
    "ProjectId",
    "RequirementId",
    "RiskId",
    "TransitionId",
    "target_type_for_id",
)
