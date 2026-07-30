"""Test-time fixture and enum coverage matrix for WP-K11."""

from __future__ import annotations

from arch_kernel.contracts import (
    CompatibilityLevel,
    ContractKind,
    ContractStatus,
    GuardType,
    InvariantKind,
    MigrationCoercion,
    MigrationOperationType,
    PatchOperationType,
    ValidationDisposition,
    ValidationIntent,
)
from tests.fixture_catalog import load_manifest


def test_fixture_classes_and_work_packages_are_represented() -> None:
    entries = load_manifest()
    classes = {item.fixture_class for item in entries}
    owners = {item.owner for item in entries}

    assert {
        "valid",
        "invalid_contract",
        "invalid_aggregate",
        "rejected_policy",
        "non_blocking_finding",
        "migration_success",
        "migration_failure",
        "regression",
    } == classes
    assert {f"WP-K{number:02d}" for number in range(1, 12)} <= owners


def test_required_closed_matrix_cells_are_inventory_complete() -> None:
    matrix = {
        "patch_operations": {item.value for item in PatchOperationType},
        "guard_kinds": {item.value for item in GuardType},
        "invariant_kinds": {item.value for item in InvariantKind},
        "validation_intents": {item.value for item in ValidationIntent},
        "validation_dispositions": {item.value for item in ValidationDisposition},
        "contract_kinds": {item.value for item in ContractKind},
        "contract_statuses": {item.value for item in ContractStatus},
        "compatibility_levels": {item.value for item in CompatibilityLevel},
        "migration_operations": {item.value for item in MigrationOperationType},
        "migration_coercions": {item.value for item in MigrationCoercion},
    }

    assert all(matrix.values())
    assert len(matrix["patch_operations"]) == len(PatchOperationType)
    assert len(matrix["guard_kinds"]) == len(GuardType)
    assert len(matrix["invariant_kinds"]) == len(InvariantKind)
    assert len(matrix["migration_operations"]) == 10
    assert len(matrix["migration_coercions"]) == 7
