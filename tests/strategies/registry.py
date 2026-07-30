"""Contract registry ordering strategies."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from arch_kernel.kernel.contract_registry import ContractRegistry
from tests.registry_helpers import CatalogModelV1, CatalogModelV2, registration


def contract_registries() -> SearchStrategy[ContractRegistry]:
    registrations = (
        registration(CatalogModelV1, version="1.0.0"),
        registration(CatalogModelV2, version="1.1.0"),
    )
    return st.permutations(registrations).map(lambda items: ContractRegistry(tuple(items)))


__all__ = ("contract_registries",)
