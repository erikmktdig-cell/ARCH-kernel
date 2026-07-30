"""Immutable dependency edge contract."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import field_validator, model_validator

from arch_kernel.contracts._validation import require_optional_non_blank
from arch_kernel.contracts.base import ImmutableRecord
from arch_kernel.contracts.references import TypedReference

DependencyType = Literal[
    "requires",
    "produces",
    "blocks",
    "supersedes",
    "validates",
    "relates_to",
]


class DependencyEdge(ImmutableRecord):
    """Directed, immutable dependency relationship between two references."""

    source: TypedReference
    target: TypedReference
    dependency_type: DependencyType
    required: bool
    reason: str | None = None

    @field_validator("reason")
    @classmethod
    def _reason_must_not_be_blank(cls, value: str | None) -> str | None:
        return require_optional_non_blank(value, field_name="reason")

    @model_validator(mode="after")
    def _validate_dependency(self) -> Self:
        if self.source == self.target:
            raise ValueError("Dependency source and target cannot be identical.")
        if self.dependency_type in {"blocks", "supersedes"} and self.reason is None:
            raise ValueError("reason is required for blocks and supersedes dependencies.")
        return self


__all__ = ("DependencyEdge", "DependencyType")
