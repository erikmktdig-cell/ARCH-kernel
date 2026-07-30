"""Route enums."""

from __future__ import annotations

from enum import StrEnum, unique


@unique
class Route(StrEnum):
    """Canonical ARch routing modes."""

    QUICK = "quick"
    STANDARD = "standard"
    CRITICAL = "critical"


__all__ = ("Route",)
