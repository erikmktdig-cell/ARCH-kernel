"""Immutable registry and built-in catalog tests for WP-K09."""

from __future__ import annotations

import pytest

from arch_kernel.contracts import (
    ContractAlias,
    ContractKind,
    ContractRegistration,
    ContractStatus,
    SemanticVersion,
)
from arch_kernel.kernel import ArchKernelError, ErrorCode
from arch_kernel.kernel.contract_registry import (
    ContractRegistry,
    build_builtin_contract_registry,
)
from tests.registry_helpers import (
    CatalogModelV1,
    CatalogModelV2,
    registration,
)


def test_builtin_registry_is_complete_ordered_and_schema_backed() -> None:
    registry = build_builtin_contract_registry()
    assert len(registry.registrations) == 35
    assert tuple(
        (item.descriptor.canonical_name, item.descriptor.version) for item in registry.registrations
    ) == tuple(
        sorted(
            (
                item.descriptor.canonical_name,
                item.descriptor.version,
            )
            for item in registry.registrations
        )
    )
    assert all(item.descriptor.schema_fingerprint for item in registry.registrations)


def test_lookup_alias_model_latest_and_filters() -> None:
    alias = ContractAlias(alias="arch.legacy.catalog_model")
    first = registration(aliases=(alias,))
    second = registration(CatalogModelV2, version="1.1.0")
    registry = ContractRegistry((second, first))
    assert registry.get(first.descriptor.canonical_name, SemanticVersion.parse("1.0.0")) is first
    assert registry.latest_active(first.descriptor.canonical_name) is second
    assert registry.resolve(alias.alias, SemanticVersion.parse("1.0.0")) is first
    assert registry.get_by_model(CatalogModelV2) is second
    assert registry.filter(kind=ContractKind.RECORD, domain="test", tag="test") == (
        first,
        second,
    )
    assert registry.filter(status=ContractStatus.DEPRECATED) == ()


def test_registry_order_and_catalog_fingerprint_ignore_insertion_order() -> None:
    first = registration()
    second = registration(
        CatalogModelV2,
        canonical_name="arch.test.second_model",
    )
    left = ContractRegistry((first, second))
    right = ContractRegistry((second, first))
    assert left.registrations == right.registrations
    assert left.catalog_fingerprint == right.catalog_fingerprint


def test_registry_rejects_duplicate_identity_alias_and_model() -> None:
    first = registration()
    with pytest.raises(ArchKernelError) as duplicate_identity:
        ContractRegistry((first, first))
    assert duplicate_identity.value.detail.code is ErrorCode.DUPLICATE_CONTRACT_IDENTITY

    alias = ContractAlias(alias="arch.legacy.shared")
    left = registration(aliases=(alias,))
    right = registration(
        CatalogModelV2,
        canonical_name="arch.test.second_model",
        aliases=(alias,),
    )
    with pytest.raises(ArchKernelError) as duplicate_alias:
        ContractRegistry((left, right))
    assert duplicate_alias.value.detail.code is ErrorCode.DUPLICATE_CONTRACT_ALIAS

    same_model = registration(
        CatalogModelV1,
        canonical_name="arch.test.second_model",
    )
    with pytest.raises(ArchKernelError) as duplicate_model:
        ContractRegistry((first, same_model))
    assert duplicate_model.value.detail.code is ErrorCode.CONTRACT_MODEL_MISMATCH


def test_registry_rejects_alias_collision_and_model_mismatch() -> None:
    canonical = registration()
    colliding = registration(
        CatalogModelV2,
        canonical_name="arch.test.second_model",
        aliases=(ContractAlias(alias=canonical.descriptor.canonical_name),),
    )
    with pytest.raises(ArchKernelError) as collision:
        ContractRegistry((canonical, colliding))
    assert collision.value.detail.code is ErrorCode.CONTRACT_ALIAS_COLLISION

    bad_descriptor = canonical.descriptor.model_copy(update={"python_qualname": "DifferentModel"})
    with pytest.raises(ArchKernelError) as mismatch:
        ContractRegistry((ContractRegistration(bad_descriptor, CatalogModelV1),))
    assert mismatch.value.detail.code is ErrorCode.CONTRACT_MODEL_MISMATCH


def test_registry_rejects_schema_fingerprint_mismatch_and_is_immutable() -> None:
    item = registration()
    bad = ContractRegistration(
        item.descriptor.model_copy(update={"schema_fingerprint": "sha256:" + ("f" * 64)}),
        item.model,
    )
    with pytest.raises(ArchKernelError, match="schema fingerprint"):
        ContractRegistry((bad,))
    registry = ContractRegistry((item,))
    with pytest.raises(AttributeError):
        registry.registrations = ()
