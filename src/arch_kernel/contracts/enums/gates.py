"""Gate enums."""

from __future__ import annotations

from enum import StrEnum, unique


@unique
class GateResult(StrEnum):
    """Canonical result of a gate evaluation."""

    PASS = "pass"
    PASS_WITH_CONDITION = "pass_with_condition"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    INVALIDATED = "invalidated"


__all__ = ("GateResult",)
