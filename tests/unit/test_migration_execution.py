"""Atomic dry-run execution tests for WP-K10 migrations."""

from __future__ import annotations

from datetime import timedelta

from arch_kernel.contracts import (
    MigrationCoercion,
    MigrationDisposition,
    MigrationOperationType,
    MigrationPolicy,
)
from arch_kernel.kernel import audit_migration_registry, run_migration_dry_run
from arch_kernel.kernel.errors import ErrorCode
from arch_kernel.kernel.event_validation import thaw_json
from arch_kernel.kernel.fingerprints import compute_fingerprint
from arch_kernel.kernel.migration_registry import MigrationRegistry
from tests.migration_helpers import (
    EVALUATED_AT,
    OperationsSource,
    OperationsTarget,
    PayloadV1,
    PayloadV2,
    PayloadV3,
    contract_registry,
    definition,
    operation,
    request,
)

OPERATIONS_NAME = "arch.test.operations_payload"


def test_dry_run_executes_all_declarative_operation_types() -> None:
    contracts = contract_registry(
        (OperationsSource, "1.0.0"),
        (OperationsTarget, "2.0.0"),
        canonical_name=OPERATIONS_NAME,
    )
    operations = (
        operation(MigrationOperationType.TEST, "/status", expected_value="old"),
        operation(
            MigrationOperationType.RENAME,
            "/name",
            from_path="/old_name",
        ),
        operation(
            MigrationOperationType.MAP_ENUM,
            "/status",
            enum_mapping={"old": "current"},
        ),
        operation(
            MigrationOperationType.COERCE,
            "/count",
            coercion=MigrationCoercion.STRING_TO_INTEGER,
        ),
        operation(
            MigrationOperationType.COPY,
            "/copied",
            from_path="/source",
        ),
        operation(MigrationOperationType.REMOVE, "/source"),
        operation(
            MigrationOperationType.MOVE,
            "/moved",
            from_path="/movable",
        ),
        operation(MigrationOperationType.REPLACE, "/replaceable", value="after"),
        operation(MigrationOperationType.SET_DEFAULT, "/defaulted", value=True),
        operation(MigrationOperationType.ADD, "/added", value="created"),
    )
    migration = definition(
        source="1.0.0",
        target="2.0.0",
        canonical_name=OPERATIONS_NAME,
        operations=operations,
    )
    registry = MigrationRegistry((migration,), contracts)
    source = {
        "old_name": "Alpha",
        "status": "old",
        "count": "7",
        "source": "copied value",
        "movable": "moved value",
        "replaceable": "before",
    }
    source_before = compute_fingerprint(source)

    result = run_migration_dry_run(
        request(
            source,
            target="2.0.0",
            canonical_name=OPERATIONS_NAME,
            policy=MigrationPolicy(expose_intermediate_payloads=True),
        ),
        registry,
        contracts,
    )

    assert result.success
    assert result.disposition is MigrationDisposition.SUCCEEDED
    assert result.target_validated
    assert thaw_json(result.final_payload) == {
        "name": "Alpha",
        "status": "current",
        "count": 7,
        "copied": "copied value",
        "moved": "moved value",
        "replaceable": "after",
        "defaulted": True,
        "added": "created",
    }
    assert len(result.step_results[0].changed_paths) == 9
    assert result.step_results[0].output_payload == result.final_payload
    assert compute_fingerprint(source) == source_before


def test_identity_dry_run_is_explicitly_not_required() -> None:
    contracts = contract_registry((PayloadV1, "1.0.0"))
    registry = MigrationRegistry((), contracts)

    result = run_migration_dry_run(
        request({"name": "alpha"}, target="1.0.0"),
        registry,
        contracts,
    )

    assert result.success
    assert result.disposition is MigrationDisposition.NOT_REQUIRED
    assert result.plan is not None
    assert result.plan.total_steps == 0
    assert result.step_results == ()
    assert thaw_json(result.final_payload) == {"name": "alpha"}


def test_operation_failure_rolls_back_entire_result() -> None:
    contracts = contract_registry((PayloadV1, "1.0.0"), (PayloadV2, "1.1.0"))
    broken = definition(
        operations=(operation(MigrationOperationType.REPLACE, "/missing", value="x"),)
    )
    registry = MigrationRegistry((broken,), contracts)

    result = run_migration_dry_run(request({"name": "alpha"}), registry, contracts)

    assert not result.success
    assert result.blocking_failure
    assert result.final_payload is None
    assert result.final_payload_fingerprint is None
    assert not result.step_results[0].success
    assert result.findings[0].code == ErrorCode.MIGRATION_OPERATION_FAILED.value


def test_target_validation_failure_does_not_expose_final_payload() -> None:
    contracts = contract_registry((PayloadV1, "1.0.0"), (PayloadV2, "1.1.0"))
    invalid_target = definition(
        operations=(operation(MigrationOperationType.ADD, "/rogue", value=True),)
    )
    registry = MigrationRegistry((invalid_target,), contracts)

    result = run_migration_dry_run(request({"name": "alpha"}), registry, contracts)

    assert not result.success
    assert result.final_payload is None
    assert result.findings[-1].code == ErrorCode.MIGRATION_TARGET_VALIDATION_FAILED.value


def test_source_validation_and_payload_precondition_fail_before_planning() -> None:
    contracts = contract_registry((PayloadV1, "1.0.0"), (PayloadV2, "1.1.0"))
    migration = definition()
    registry = MigrationRegistry((migration,), contracts)

    invalid = run_migration_dry_run(request({"name": 3}), registry, contracts)
    stale_request = request({"name": "alpha"}).model_copy(
        update={"expected_source_payload_fingerprint": "sha256:" + ("0" * 64)}
    )
    stale = run_migration_dry_run(stale_request, registry, contracts)

    assert invalid.plan is None
    assert invalid.findings[0].code == ErrorCode.MIGRATION_SOURCE_VALIDATION_FAILED.value
    assert stale.plan is None
    assert stale.findings[0].code == ErrorCode.MIGRATION_PRECONDITION_FAILED.value


def test_multistep_failure_is_atomic_and_intermediates_are_opt_in() -> None:
    contracts = contract_registry(
        (PayloadV1, "1.0.0"),
        (PayloadV2, "1.1.0"),
        (PayloadV3, "1.2.0"),
    )
    first = definition(index=0, source="1.0.0", target="1.1.0")
    second = definition(
        index=1,
        source="1.1.0",
        target="1.2.0",
        operations=(operation(MigrationOperationType.REPLACE, "/missing", value="x"),),
    )
    registry = MigrationRegistry((first, second), contracts)

    result = run_migration_dry_run(
        request({"name": "alpha"}, target="1.2.0"),
        registry,
        contracts,
    )

    assert not result.success
    assert len(result.step_results) == 2
    assert result.step_results[0].success
    assert result.step_results[0].output_payload is None
    assert result.final_payload is None


def test_reversible_pair_round_trips_and_audits_cleanly() -> None:
    contracts = contract_registry((PayloadV1, "1.0.0"), (PayloadV2, "1.1.0"))
    upgrade = definition(index=0, reversible=True, reverse_index=1)
    downgrade = definition(
        index=1,
        source="1.1.0",
        target="1.0.0",
        operations=(operation(MigrationOperationType.REMOVE, "/note"),),
        reversible=True,
        reverse_index=0,
    )
    registry = MigrationRegistry((upgrade, downgrade), contracts)
    source = {"name": "alpha"}
    up = run_migration_dry_run(request(source), registry, contracts)
    upgraded_payload = thaw_json(up.final_payload)
    assert isinstance(upgraded_payload, dict)
    down = run_migration_dry_run(
        request(
            upgraded_payload,
            source="1.1.0",
            target="1.0.0",
            policy=MigrationPolicy(allow_downgrade=True),
        ),
        registry,
        contracts,
    )

    assert up.success
    assert down.success
    assert thaw_json(down.final_payload) == source
    assert audit_migration_registry(registry, contracts).success


def test_result_fingerprint_excludes_evaluation_time() -> None:
    contracts = contract_registry((PayloadV1, "1.0.0"), (PayloadV2, "1.1.0"))
    registry = MigrationRegistry((definition(),), contracts)
    first_request = request({"name": "alpha"})
    second_request = first_request.model_copy(
        update={"evaluated_at": EVALUATED_AT + timedelta(hours=1)}
    )

    first = run_migration_dry_run(first_request, registry, contracts)
    second = run_migration_dry_run(second_request, registry, contracts)

    assert first.result_fingerprint == second.result_fingerprint
    assert first.evaluated_at != second.evaluated_at


def test_audit_rejects_false_identity_migration() -> None:
    contracts = contract_registry(
        (PayloadV1, "1.0.0"),
        (PayloadV2, "1.1.0"),
    )
    identity = definition(operations=(), identity=True)
    registry = MigrationRegistry((identity,), contracts)

    report = audit_migration_registry(registry, contracts)

    assert not report.success
    assert report.findings[0].code == ErrorCode.INVALID_MIGRATION_DEFINITION.value
