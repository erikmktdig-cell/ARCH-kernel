"""Metamorphic properties for the K10 migration framework."""

from __future__ import annotations

from arch_kernel.contracts import MigrationDisposition
from arch_kernel.kernel import run_migration_dry_run
from arch_kernel.kernel.event_validation import thaw_json
from arch_kernel.kernel.migration_registry import MigrationRegistry
from tests.migration_helpers import (
    PayloadV1,
    PayloadV2,
    contract_registry,
    definition,
    request,
)


def test_source_equals_target_is_zero_step_not_required() -> None:
    contracts = contract_registry((PayloadV1, "1.0.0"))
    result = run_migration_dry_run(
        request({"name": "alpha"}, target="1.0.0"),
        MigrationRegistry((), contracts),
        contracts,
    )

    assert result.disposition is MigrationDisposition.NOT_REQUIRED
    assert result.plan is not None
    assert result.plan.total_steps == 0


def test_semantic_payload_change_changes_result_fingerprint() -> None:
    contracts = contract_registry((PayloadV1, "1.0.0"), (PayloadV2, "1.1.0"))
    registry = MigrationRegistry((definition(),), contracts)

    first = run_migration_dry_run(request({"name": "alpha"}), registry, contracts)
    second = run_migration_dry_run(request({"name": "beta"}), registry, contracts)

    assert first.success
    assert second.success
    assert first.result_fingerprint != second.result_fingerprint
    assert thaw_json(first.final_payload) != thaw_json(second.final_payload)
