"""Registry, graph, planning, and audit tests for WP-K10."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from arch_kernel.contracts import (
    MigrationDefinition,
    MigrationOperationType,
    MigrationPolicy,
    MigrationStatus,
    SemanticVersion,
)
from arch_kernel.kernel import audit_migration_registry, resolve_migration_plan
from arch_kernel.kernel.contract_registry import ContractRegistry
from arch_kernel.kernel.errors import ArchKernelError, ErrorCode
from arch_kernel.kernel.migration_registry import MigrationRegistry
from tests.migration_helpers import (
    CANONICAL_NAME,
    PayloadV1,
    PayloadV2,
    PayloadV3,
    PayloadV4,
    contract_registry,
    definition,
    migration_registry,
    operation,
    request,
)


def _catalog() -> ContractRegistry:
    return contract_registry(
        (PayloadV1, "1.0.0"),
        (PayloadV2, "1.1.0"),
        (PayloadV3, "1.2.0"),
        (PayloadV4, "2.0.0"),
    )


def test_registry_orders_indexes_filters_and_fingerprints_deterministically() -> None:
    contracts = _catalog()
    first = definition(index=0, source="1.0.0", target="1.1.0")
    second = definition(index=1, source="1.1.0", target="1.2.0")
    registry = migration_registry((second, first), contracts)
    rebuilt = migration_registry((first, second), contracts)

    assert registry.definitions == (first, second)
    assert registry.get_by_id(first.migration_id) is first
    assert registry.get_by_key(second.key) is second
    assert (
        registry.get_edge(
            CANONICAL_NAME,
            SemanticVersion.parse("1.0.0"),
            SemanticVersion.parse("1.1.0"),
        )
        is first
    )
    assert registry.outgoing(CANONICAL_NAME, first.source_version) == (first,)
    assert registry.incoming(CANONICAL_NAME, first.target_version) == (first,)
    assert registry.filter(lossless=True) == (first, second)
    assert registry.registry_fingerprint == rebuilt.registry_fingerprint

    with pytest.raises(AttributeError):
        registry.registry_fingerprint = "changed"


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (
            lambda first: first.model_copy(
                update={
                    "key": "migration.duplicate_key",
                    "migration_id": first.migration_id,
                    "source_version": SemanticVersion.parse("1.1.0"),
                    "target_version": SemanticVersion.parse("1.2.0"),
                }
            ),
            ErrorCode.DUPLICATE_MIGRATION_ID,
        ),
        (
            lambda first: first.model_copy(
                update={
                    "migration_id": definition(index=1).migration_id,
                    "source_version": SemanticVersion.parse("1.1.0"),
                    "target_version": SemanticVersion.parse("1.2.0"),
                }
            ),
            ErrorCode.DUPLICATE_MIGRATION_KEY,
        ),
        (
            lambda first: first.model_copy(
                update={
                    "migration_id": definition(index=1).migration_id,
                    "key": "migration.duplicate_edge",
                }
            ),
            ErrorCode.DUPLICATE_MIGRATION_EDGE,
        ),
    ],
)
def test_registry_rejects_duplicate_graph_identity(
    mutator: Callable[[MigrationDefinition], MigrationDefinition],
    code: ErrorCode,
) -> None:
    contracts = _catalog()
    first = definition()
    duplicate = mutator(first)

    with pytest.raises(ArchKernelError) as captured:
        MigrationRegistry((first, duplicate), contracts)

    assert captured.value.detail.code is code


def test_registry_rejects_missing_active_endpoint_and_stale_schema() -> None:
    contracts = contract_registry((PayloadV1, "1.0.0"))
    active = definition()

    with pytest.raises(ArchKernelError) as missing:
        MigrationRegistry((active,), contracts)
    assert missing.value.detail.code is ErrorCode.MIGRATION_ENDPOINT_NOT_FOUND

    complete = contract_registry((PayloadV1, "1.0.0"), (PayloadV2, "1.1.0"))
    stale = active.model_copy(update={"source_schema_fingerprint": "sha256:" + ("0" * 64)})
    with pytest.raises(ArchKernelError) as fingerprint:
        MigrationRegistry((stale,), complete)
    assert fingerprint.value.detail.code is ErrorCode.MIGRATION_SCHEMA_FINGERPRINT_MISMATCH


def test_registry_requires_reciprocal_reverse_edges() -> None:
    contracts = contract_registry((PayloadV1, "1.0.0"), (PayloadV2, "1.1.0"))
    forward = definition(index=0, reversible=True, reverse_index=1)

    with pytest.raises(ArchKernelError) as captured:
        MigrationRegistry((forward,), contracts)

    assert captured.value.detail.code is ErrorCode.MIGRATION_REVERSIBILITY_INVALID


def test_planning_identity_one_step_and_multi_step() -> None:
    contracts = _catalog()
    first = definition(index=0, source="1.0.0", target="1.1.0")
    second = definition(index=1, source="1.1.0", target="1.2.0")
    registry = MigrationRegistry((first, second), contracts)

    identity = resolve_migration_plan(
        request({"name": "x"}, target="1.0.0"),
        registry,
        contracts,
    )
    one = resolve_migration_plan(request({"name": "x"}), registry, contracts)
    multi = resolve_migration_plan(
        request({"name": "x"}, target="1.2.0"),
        registry,
        contracts,
    )

    assert identity.total_steps == 0
    assert identity.direction is None
    assert one.migration_ids == (first.migration_id,)
    assert multi.migration_ids == (first.migration_id, second.migration_id)


def test_planning_rejects_downgrade_without_policy() -> None:
    contracts = contract_registry((PayloadV1, "1.0.0"), (PayloadV2, "1.1.0"))
    downgrade = definition(
        index=0,
        source="1.1.0",
        target="1.0.0",
        operations=(operation(MigrationOperationType.REMOVE, "/note"),),
    )
    registry = MigrationRegistry((downgrade,), contracts)

    with pytest.raises(ArchKernelError) as captured:
        resolve_migration_plan(
            request({"name": "x", "note": None}, source="1.1.0", target="1.0.0"),
            registry,
            contracts,
        )
    assert captured.value.detail.code is ErrorCode.MIGRATION_POLICY_VIOLATION

    plan = resolve_migration_plan(
        request(
            {"name": "x", "note": None},
            source="1.1.0",
            target="1.0.0",
            policy=MigrationPolicy(allow_downgrade=True),
        ),
        registry,
        contracts,
    )
    assert plan.total_steps == 1


def test_planning_rejects_missing_and_ambiguous_routes() -> None:
    contracts = _catalog()
    direct = definition(index=0, source="1.0.0", target="1.1.0")
    sparse = MigrationRegistry((direct,), contracts)
    with pytest.raises(ArchKernelError) as missing:
        resolve_migration_plan(
            request({"name": "x"}, target="2.0.0"),
            sparse,
            contracts,
        )
    assert missing.value.detail.code is ErrorCode.MIGRATION_PATH_NOT_FOUND

    edges = (
        definition(index=0, source="1.0.0", target="1.1.0"),
        definition(index=1, source="1.1.0", target="2.0.0"),
        definition(index=2, source="1.0.0", target="1.2.0"),
        definition(index=3, source="1.2.0", target="2.0.0"),
    )
    ambiguous = MigrationRegistry(edges, contracts)
    with pytest.raises(ArchKernelError) as conflict:
        resolve_migration_plan(
            request({"name": "x"}, target="2.0.0"),
            ambiguous,
            contracts,
        )
    assert conflict.value.detail.code is ErrorCode.AMBIGUOUS_MIGRATION_PATH

    audit = audit_migration_registry(ambiguous, contracts)
    assert not audit.success
    assert any(item.code == ErrorCode.AMBIGUOUS_MIGRATION_PATH.value for item in audit.findings)


def test_deprecated_and_selection_filters_are_explicit() -> None:
    contracts = contract_registry((PayloadV1, "1.0.0"), (PayloadV2, "1.1.0"))
    deprecated = definition(status=MigrationStatus.DEPRECATED)
    registry = MigrationRegistry((deprecated,), contracts)

    with pytest.raises(ArchKernelError):
        resolve_migration_plan(request({"name": "x"}), registry, contracts)

    selected = request(
        {"name": "x"},
        policy=MigrationPolicy(allow_deprecated=True),
    ).model_copy(update={"selected_migration_keys": (deprecated.key,)})
    assert resolve_migration_plan(selected, registry, contracts).total_steps == 1


def test_planning_reports_step_limit_as_policy_violation() -> None:
    contracts = _catalog()
    first = definition(index=0, source="1.0.0", target="1.1.0")
    second = definition(index=1, source="1.1.0", target="1.2.0")
    registry = MigrationRegistry((first, second), contracts)

    with pytest.raises(ArchKernelError) as captured:
        resolve_migration_plan(
            request(
                {"name": "x"},
                target="1.2.0",
                policy=MigrationPolicy(maximum_steps=1),
            ),
            registry,
            contracts,
        )

    assert captured.value.detail.code is ErrorCode.MIGRATION_POLICY_VIOLATION
