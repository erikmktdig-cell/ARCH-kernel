"""Execution status enums."""

from __future__ import annotations

from enum import StrEnum, unique


@unique
class ExecutionStatus(StrEnum):
    """Canonical execution status values."""

    COMPLETED = "completed"
    COMPLETED_WITH_CONDITIONS = "completed_with_conditions"
    BLOCKED = "blocked"
    NEEDS_REVIEW = "needs_review"
    CONFLICT_DETECTED = "conflict_detected"
    INVALID_INPUT = "invalid_input"
    STOPPED = "stopped"


__all__ = ("ExecutionStatus",)
