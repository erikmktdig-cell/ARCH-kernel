"""Explicit ProjectState v1-to-v2 compatibility migration."""

from arch_kernel.contracts.ids import MigrationId
from arch_kernel.contracts.migrations import (
    MigrationDefinition,
    MigrationDirection,
    MigrationOperation,
    MigrationOperationType,
    MigrationStatus,
)
from arch_kernel.contracts.versions import SemanticVersion

PROJECT_STATE_CONTRACT_NAME = "arch.project.project_state"
PROJECT_STATE_V1 = SemanticVersion.parse("1.0.0")
PROJECT_STATE_V2 = SemanticVersion.parse("2.0.0")


def _operation(
    operation_type: MigrationOperationType,
    path: str,
    **values: object,
) -> MigrationOperation:
    return MigrationOperation.model_validate(
        {"operation_type": operation_type, "path": path, **values}
    )


def build_project_state_v1_to_v2_migration() -> MigrationDefinition:
    """Return the explicit structural migration with an empty workflow registry."""

    return MigrationDefinition(
        migration_id=MigrationId.from_str("MIG-01HZX7M3FQ1T2Q9V8Y6K4C2B1Z"),
        key="project.state_add_workflow_registry",
        title="Add generic workflow registry",
        description="Upgrade ProjectState without inventing downstream workflow authority.",
        canonical_name=PROJECT_STATE_CONTRACT_NAME,
        source_version=PROJECT_STATE_V1,
        target_version=PROJECT_STATE_V2,
        direction=MigrationDirection.UPGRADE,
        status=MigrationStatus.ACTIVE,
        priority=0,
        operations=(
            _operation(
                MigrationOperationType.TEST,
                "/contract_version",
                expected_value="1.0.0",
            ),
            _operation(
                MigrationOperationType.ADD,
                "/workflow_registry",
                value={},
            ),
            _operation(
                MigrationOperationType.REPLACE,
                "/contract_version",
                value="2.0.0",
            ),
            _operation(
                MigrationOperationType.REPLACE,
                "/schema_uri",
                value="urn:arch:contracts:project_state:2.0.0",
            ),
        ),
        identity=False,
        lossless=True,
        reversible=False,
        notes="Existing v1 states migrate with no initialized workflows.",
        remediation_hint="Initialize downstream workflows through an explicit governed command.",
        contract_version=SemanticVersion.parse("1.0.0"),
        schema_uri="urn:arch:contracts:migration_definition:1.0.0",
    )


__all__ = (
    "PROJECT_STATE_CONTRACT_NAME",
    "PROJECT_STATE_V1",
    "PROJECT_STATE_V2",
    "build_project_state_v1_to_v2_migration",
)
