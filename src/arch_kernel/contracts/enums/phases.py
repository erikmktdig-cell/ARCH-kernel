"""Phase enums."""

from __future__ import annotations

from enum import StrEnum, unique


@unique
class PhaseCode(StrEnum):
    """Canonical ARch phase codes."""

    F01 = "F01"
    F02 = "F02"
    F03 = "F03"
    F04 = "F04"
    F05 = "F05"
    F06 = "F06"
    F07 = "F07"
    F08 = "F08"
    F09 = "F09"
    F10 = "F10"
    F11 = "F11"
    F12 = "F12"
    F13 = "F13"
    F14 = "F14"
    F15 = "F15"


@unique
class PhaseStatus(StrEnum):
    """Canonical lifecycle status for phase execution."""

    NOT_STARTED = "not_started"
    ELIGIBLE = "eligible"
    READY = "ready"
    ACTIVE = "active"
    BLOCKED = "blocked"
    AWAITING_APPROVAL = "awaiting_approval"
    IN_REVIEW = "in_review"
    COMPLETED = "completed"
    COMPLETED_WITH_CONDITIONS = "completed_with_conditions"
    REVALIDATION_PENDING = "revalidation_pending"
    REOPENED = "reopened"
    CANCELLED = "cancelled"


__all__ = ("PhaseCode", "PhaseStatus")
