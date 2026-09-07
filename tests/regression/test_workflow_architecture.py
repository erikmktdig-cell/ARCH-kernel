"""Architecture and legacy compatibility guards for C01."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import get_args

from arch_kernel.contracts import (
    ApprovalDecision,
    ArtifactStatus,
    PhaseCode,
    PhaseStatus,
    RequirementStatus,
    RiskStatus,
    TransitionDomain,
)

ROOT = Path(__file__).parents[2]
SOURCE = ROOT / "src" / "arch_kernel"


def test_workflow_mechanics_have_no_downstream_vocabulary_or_dependencies() -> None:
    forbidden_text = (
        "arch_web",
        "DRAFT",
        "REQUIREMENTS_APPROVED",
        "frontend",
        "backend",
        "React",
        "CoachOps",
    )
    forbidden_imports = ("arch_runtime", "arch_web", "sqlite3", "sqlalchemy", "fastapi")

    for path in SOURCE.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if path.name in {"workflows.py", "workflow_registry.py", "project_state_migration.py"}:
            assert not any(value in source for value in forbidden_text)
        tree = ast.parse(source)
        imported = tuple(
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        ) + tuple(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not any(name.startswith(forbidden_imports) for name in imported)


def test_public_legacy_enums_are_unchanged_except_authorized_new_domain() -> None:
    assert tuple(item.value for item in PhaseCode) == tuple(
        f"F{index:02d}" for index in range(1, 16)
    )
    assert tuple(item.value for item in PhaseStatus) == (
        "not_started",
        "eligible",
        "ready",
        "active",
        "blocked",
        "awaiting_approval",
        "in_review",
        "completed",
        "completed_with_conditions",
        "revalidation_pending",
        "reopened",
        "cancelled",
    )
    assert tuple(item.value for item in TransitionDomain) == (
        "project_lifecycle",
        "phase_status",
        "artifact_status",
        "approval_decision",
        "risk_status",
        "requirement_status",
        "workflow_state",
    )
    assert tuple(item.value for item in ArtifactStatus) == (
        "draft",
        "proposed",
        "under_review",
        "changes_requested",
        "conditionally_approved",
        "approved",
        "rejected",
        "invalidated",
        "superseded",
        "archived",
    )
    assert tuple(item.value for item in ApprovalDecision) == (
        "approved",
        "approved_with_conditions",
        "rejected",
        "deferred",
        "revoked",
        "expired",
    )
    assert get_args(RequirementStatus) == (
        "proposed",
        "accepted",
        "implemented",
        "verified",
        "rejected",
        "deferred",
    )
    assert get_args(RiskStatus) == (
        "open",
        "mitigating",
        "accepted",
        "closed",
        "materialized",
    )
