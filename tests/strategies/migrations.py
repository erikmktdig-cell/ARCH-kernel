"""Migration registry and request strategies."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from arch_kernel.contracts import MigrationRequest
from arch_kernel.kernel.migration_registry import MigrationRegistry
from tests.migration_helpers import (
    PayloadV1,
    PayloadV2,
    contract_registry,
    definition,
    request,
)


def migration_registries() -> SearchStrategy[MigrationRegistry]:
    contracts = contract_registry((PayloadV1, "1.0.0"), (PayloadV2, "1.1.0"))
    return st.just(MigrationRegistry((definition(),), contracts))


def migration_requests() -> SearchStrategy[MigrationRequest]:
    return st.text(max_size=30).map(lambda name: request({"name": name}))


__all__ = ("migration_registries", "migration_requests")
