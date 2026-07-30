"""Semantic version primitive for ARch contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering
from types import NotImplementedType
from typing import Any, ClassVar, Self

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

from arch_kernel.kernel.errors import VersionValidationError

_IDENTIFIER_RE = re.compile(r"^[0-9A-Za-z-]+$")
_SEMVER_PATTERN = (
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_SEMVER_RE = re.compile(_SEMVER_PATTERN)


def _validate_core_part(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise VersionValidationError(
            f"Semantic version {name} must be an integer.",
            path=(name,),
            expected="non-negative integer",
            actual=type(value).__name__,
        )
    if value < 0:
        raise VersionValidationError(
            f"Semantic version {name} must be non-negative.",
            path=(name,),
            expected="non-negative integer",
            actual=value,
        )
    return value


def _validate_identifier(identifier: object, *, field_name: str, allow_leading_zero: bool) -> str:
    if not isinstance(identifier, str) or identifier == "":
        raise VersionValidationError(
            f"Semantic version {field_name} identifiers must be non-empty strings.",
            path=(field_name,),
            expected="non-empty identifier",
            actual=type(identifier).__name__,
        )
    if _IDENTIFIER_RE.fullmatch(identifier) is None:
        raise VersionValidationError(
            f"Semantic version {field_name} identifier contains invalid characters.",
            path=(field_name,),
            expected="ASCII alphanumerics and hyphen",
            actual=identifier,
        )
    has_leading_zero = identifier.startswith("0") and len(identifier) > 1
    if not allow_leading_zero and identifier.isdigit() and has_leading_zero:
        raise VersionValidationError(
            "Numeric prerelease identifiers must not contain leading zeroes.",
            path=(field_name,),
            expected="numeric identifier without leading zeroes",
            actual=identifier,
        )
    return identifier


def _validate_identifier_tuple(
    value: object,
    *,
    field_name: str,
    allow_leading_zero: bool,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise VersionValidationError(
            f"Semantic version {field_name} must be a tuple of identifiers.",
            path=(field_name,),
            expected="tuple[str, ...]",
            actual=type(value).__name__,
        )
    return tuple(
        _validate_identifier(
            identifier,
            field_name=field_name,
            allow_leading_zero=allow_leading_zero,
        )
        for identifier in value
    )


def _compare_prerelease(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    if left == right:
        return 0
    if not left:
        return 1
    if not right:
        return -1

    for left_identifier, right_identifier in zip(left, right, strict=False):
        if left_identifier == right_identifier:
            continue

        left_is_numeric = left_identifier.isdigit()
        right_is_numeric = right_identifier.isdigit()

        if left_is_numeric and right_is_numeric:
            left_value = int(left_identifier)
            right_value = int(right_identifier)
            return -1 if left_value < right_value else 1
        if left_is_numeric != right_is_numeric:
            return -1 if left_is_numeric else 1
        return -1 if left_identifier < right_identifier else 1

    return -1 if len(left) < len(right) else 1


@total_ordering
@dataclass(frozen=True, slots=True, eq=False)
class SemanticVersion:
    """Immutable SemVer 2.0.0 value object.

    Equality and hashing follow SemVer precedence and intentionally ignore build
    metadata. Use ``is_identical_to`` when build metadata identity matters.
    """

    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: tuple[str, ...] = ()

    pattern: ClassVar[str] = _SEMVER_PATTERN

    def __post_init__(self) -> None:
        _validate_core_part("major", self.major)
        _validate_core_part("minor", self.minor)
        _validate_core_part("patch", self.patch)
        _validate_identifier_tuple(
            self.prerelease,
            field_name="prerelease",
            allow_leading_zero=False,
        )
        _validate_identifier_tuple(
            self.build,
            field_name="build",
            allow_leading_zero=True,
        )

    @classmethod
    def parse(cls, value: str) -> Self:
        """Parse a SemVer 2.0.0 string."""

        if not isinstance(value, str):
            raise VersionValidationError(
                "SemanticVersion.parse expects a string.",
                expected="SemVer string",
                actual=type(value).__name__,
            )
        match = _SEMVER_RE.fullmatch(value)
        if match is None:
            raise VersionValidationError(
                "Semantic version string is not valid SemVer 2.0.0.",
                expected="SemVer 2.0.0 string",
                actual=value,
            )

        prerelease = tuple(match.group(4).split(".")) if match.group(4) else ()
        build = tuple(match.group(5).split(".")) if match.group(5) else ()
        return cls(
            major=int(match.group(1)),
            minor=int(match.group(2)),
            patch=int(match.group(3)),
            prerelease=prerelease,
            build=build,
        )

    def __str__(self) -> str:
        value = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            value = f"{value}-{'.'.join(self.prerelease)}"
        if self.build:
            value = f"{value}+{'.'.join(self.build)}"
        return value

    def __repr__(self) -> str:
        return f"SemanticVersion.parse({str(self)!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SemanticVersion):
            return False
        return (
            self.major,
            self.minor,
            self.patch,
            self.prerelease,
        ) == (
            other.major,
            other.minor,
            other.patch,
            other.prerelease,
        )

    def __hash__(self) -> int:
        return hash((self.major, self.minor, self.patch, self.prerelease))

    def __lt__(self, other: object) -> bool | NotImplementedType:
        if not isinstance(other, SemanticVersion):
            return NotImplemented

        left_core = (self.major, self.minor, self.patch)
        right_core = (other.major, other.minor, other.patch)
        if left_core != right_core:
            return left_core < right_core

        return _compare_prerelease(self.prerelease, other.prerelease) < 0

    def is_identical_to(self, other: SemanticVersion) -> bool:
        """Return true only when build metadata also matches."""

        return (
            self.major,
            self.minor,
            self.patch,
            self.prerelease,
            self.build,
        ) == (
            other.major,
            other.minor,
            other.patch,
            other.prerelease,
            other.build,
        )

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        from_string_schema = core_schema.no_info_after_validator_function(
            cls.parse,
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
            "pattern": cls.pattern,
            "examples": [
                "1.0.0",
                "1.2.3-alpha.1",
                "1.2.3-rc.1+sha.abc123",
            ],
        }


__all__ = ("SemanticVersion",)
