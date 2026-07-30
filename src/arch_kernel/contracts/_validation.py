"""Small shared validators for WP-K03 contract models."""

from __future__ import annotations

import re
from collections.abc import Collection

from arch_kernel.contracts.enums import PhaseStatus

SHA256_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
TERMINAL_PHASE_STATUSES = frozenset(
    {
        PhaseStatus.COMPLETED,
        PhaseStatus.COMPLETED_WITH_CONDITIONS,
        PhaseStatus.CANCELLED,
    }
)


def require_non_blank(value: str, *, field_name: str) -> str:
    """Reject empty or whitespace-only text without changing its value."""

    if value.strip() == "":
        raise ValueError(f"{field_name} cannot be empty.")
    return value


def require_optional_non_blank(value: str | None, *, field_name: str) -> str | None:
    """Validate optional text when it is present."""

    if value is None:
        return None
    return require_non_blank(value, field_name=field_name)


def require_unique(values: Collection[object], *, field_name: str) -> Collection[object]:
    """Reject exact duplicate hashable values in a contract collection."""

    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} cannot contain duplicate values.")
    return values


__all__ = (
    "SHA256_FINGERPRINT_RE",
    "TERMINAL_PHASE_STATUSES",
    "require_non_blank",
    "require_optional_non_blank",
    "require_unique",
)
