"""Property-style determinism checks for WP-K10."""

from __future__ import annotations

from arch_kernel.kernel import resolve_migration_plan, run_migration_dry_run
from arch_kernel.kernel.event_validation import thaw_json
from arch_kernel.kernel.fingerprints import compute_fingerprint
from arch_kernel.kernel.migration_registry import MigrationRegistry
from tests.migration_helpers import (
    PayloadV1,
    PayloadV2,
    PayloadV3,
    contract_registry,
    definition,
    request,
)


def test_registry_and_plan_ignore_definition_insertion_order() -> None:
    contracts = contract_registry(
        (PayloadV1, "1.0.0"),
        (PayloadV2, "1.1.0"),
        (PayloadV3, "1.2.0"),
    )
    first = definition(index=0, source="1.0.0", target="1.1.0")
    second = definition(index=1, source="1.1.0", target="1.2.0")
    left = MigrationRegistry((first, second), contracts)
    right = MigrationRegistry((second, first), contracts)
    migration_request = request({"name": "alpha"}, target="1.2.0")

    left_plan = resolve_migration_plan(migration_request, left, contracts)
    right_plan = resolve_migration_plan(migration_request, right, contracts)

    assert left.registry_fingerprint == right.registry_fingerprint
    assert left_plan.plan_fingerprint == right_plan.plan_fingerprint
    assert left_plan.migration_ids == right_plan.migration_ids


def test_repeated_dry_runs_are_pure_and_deterministic() -> None:
    contracts = contract_registry((PayloadV1, "1.0.0"), (PayloadV2, "1.1.0"))
    registry = MigrationRegistry((definition(),), contracts)
    payload = {"name": "alpha"}
    before = compute_fingerprint(payload)
    migration_request = request(payload)

    first = run_migration_dry_run(migration_request, registry, contracts)
    second = run_migration_dry_run(migration_request, registry, contracts)

    assert first == second
    assert first.result_fingerprint == second.result_fingerprint
    assert compute_fingerprint(payload) == before
    assert thaw_json(first.final_payload) == {"name": "alpha", "note": None}
