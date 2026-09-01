"""Explicit C01 ProjectState v1-to-v2 migration evidence."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from arch_kernel.contracts import (
    ArtifactId,
    ArtifactRecord,
    DecisionRecord,
    DependencyEdge,
    LifecycleState,
    MigrationRequest,
    PhaseExecutionRecord,
    PhaseId,
    ProjectMetadata,
    ProjectProfile,
    ProjectState,
    RequirementId,
    RequirementRecord,
    RiskId,
    RiskRecord,
)
from arch_kernel.kernel import build_project_state_v1_to_v2_migration, run_migration_dry_run
from arch_kernel.kernel.contract_registry import ContractRegistry
from arch_kernel.kernel.event_validation import freeze_json_object, thaw_json
from arch_kernel.kernel.fingerprints import canonicalize_json
from arch_kernel.kernel.migration_registry import MigrationRegistry
from tests.migration_helpers import EVALUATED_AT
from tests.registry_helpers import registration

FIXTURE = Path(__file__).parents[2] / "fixtures" / "valid" / "minimal_project_state.json"
CANONICAL_NAME = "arch.project.project_state"


class LegacyProjectStateV1(BaseModel):
    """Exact representative v1 shape, intentionally without workflows."""

    model_config = ConfigDict(extra="forbid", strict=True)

    contract_name: str
    contract_version: str
    schema_uri: str
    created_at: datetime
    updated_at: datetime | None
    record_version: int
    state_version_created: int
    state_version_updated: int
    metadata: ProjectMetadata
    profile: ProjectProfile
    lifecycle: LifecycleState
    phase_execution_records: dict[PhaseId, PhaseExecutionRecord]
    artifact_registry: dict[ArtifactId, ArtifactRecord]
    requirement_registry: dict[RequirementId, RequirementRecord]
    risk_registry: dict[RiskId, RiskRecord]
    decision_log: tuple[DecisionRecord, ...]
    dependency_graph: tuple[DependencyEdge, ...]
    active_baseline_artifact_ids: tuple[ArtifactId, ...]
    open_items: tuple[str, ...]


def _legacy_payload() -> dict[str, object]:
    payload = ProjectState.model_validate_json(FIXTURE.read_text(encoding="utf-8")).model_dump(
        mode="json"
    )
    del payload["workflow_registry"]
    payload["contract_version"] = "1.0.0"
    payload["schema_uri"] = "urn:arch:contracts:project_state:1.0.0"
    return payload


def test_v2_project_state_requires_explicit_workflow_collection() -> None:
    payload = _legacy_payload()
    payload["contract_version"] = "2.0.0"
    payload["schema_uri"] = "urn:arch:contracts:project_state:2.0.0"

    with pytest.raises(ValidationError, match="workflow_registry"):
        ProjectState.model_validate(payload)


def test_v1_to_v2_migration_creates_no_invented_workflow() -> None:
    contracts = ContractRegistry(
        (
            registration(LegacyProjectStateV1, canonical_name=CANONICAL_NAME, version="1.0.0"),
            registration(ProjectState, canonical_name=CANONICAL_NAME, version="2.0.0"),
        )
    )
    migration = build_project_state_v1_to_v2_migration()
    registry = MigrationRegistry((migration,), contracts)
    payload = _legacy_payload()
    request = MigrationRequest(
        canonical_name=CANONICAL_NAME,
        source_version=migration.source_version,
        target_version=migration.target_version,
        source_payload=freeze_json_object(payload),
        evaluated_at=EVALUATED_AT,
    )

    result = run_migration_dry_run(request, registry, contracts)
    migrated = thaw_json(result.final_payload)

    assert result.success
    assert isinstance(migrated, dict)
    assert migrated["workflow_registry"] == {}
    assert migrated["contract_version"] == "2.0.0"
    assert ProjectState.model_validate_json(canonicalize_json(migrated)).workflow_registry == {}
