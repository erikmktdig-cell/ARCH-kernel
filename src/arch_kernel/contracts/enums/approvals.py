"""Approval enums."""

from __future__ import annotations

from enum import StrEnum, unique


@unique
class ApprovalDecision(StrEnum):
    """Canonical approval decisions."""

    APPROVED = "approved"
    APPROVED_WITH_CONDITIONS = "approved_with_conditions"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    REVOKED = "revoked"
    EXPIRED = "expired"


__all__ = ("ApprovalDecision",)
