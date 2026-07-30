"""Artifact enums."""

from __future__ import annotations

from enum import StrEnum, unique


@unique
class ArtifactStatus(StrEnum):
    """Canonical artifact lifecycle status."""

    DRAFT = "draft"
    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    CHANGES_REQUESTED = "changes_requested"
    CONDITIONALLY_APPROVED = "conditionally_approved"
    APPROVED = "approved"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


__all__ = ("ArtifactStatus",)
