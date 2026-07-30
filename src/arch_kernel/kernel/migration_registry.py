"""Immutable explicit migration edge registry and version graph indexes."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from arch_kernel.contracts.ids import MigrationId
from arch_kernel.contracts.migrations import (
    MigrationDefinition,
    MigrationDirection,
    MigrationStatus,
)
from arch_kernel.contracts.versions import SemanticVersion
from arch_kernel.kernel.contract_registry import ContractRegistry
from arch_kernel.kernel.errors import ArchKernelError, ErrorCode, ErrorDetail, Severity
from arch_kernel.kernel.fingerprints import compute_fingerprint
from arch_kernel.kernel.schema_generation import generate_contract_schema


def _error(code: ErrorCode, message: str, actual: str) -> ArchKernelError:
    return ArchKernelError(
        ErrorDetail(
            code=code,
            message=message,
            path=("migrations",),
            entity_type="migration_registry",
            actual=actual,
            severity=Severity.ERROR,
        )
    )


class MigrationRegistry:
    """Immutable deterministic migration graph bound to one contract catalog."""

    __slots__ = (
        "_by_edge",
        "_by_id",
        "_by_key",
        "_incoming",
        "_outgoing",
        "contract_registry",
        "definitions",
        "registry_fingerprint",
    )

    definitions: tuple[MigrationDefinition, ...]
    contract_registry: ContractRegistry
    registry_fingerprint: str
    _by_id: Mapping[MigrationId, MigrationDefinition]
    _by_key: Mapping[str, MigrationDefinition]
    _by_edge: Mapping[tuple[str, SemanticVersion, SemanticVersion], MigrationDefinition]
    _outgoing: Mapping[tuple[str, SemanticVersion], tuple[MigrationDefinition, ...]]
    _incoming: Mapping[tuple[str, SemanticVersion], tuple[MigrationDefinition, ...]]

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("MigrationRegistry is immutable.")

    def __init__(
        self,
        definitions: tuple[MigrationDefinition, ...],
        contract_registry: ContractRegistry,
    ) -> None:
        if not isinstance(definitions, tuple):
            raise TypeError("MigrationRegistry definitions must be a tuple.")
        if not isinstance(contract_registry, ContractRegistry):
            raise TypeError("contract_registry must be a ContractRegistry.")
        ordered = tuple(
            sorted(
                definitions,
                key=lambda item: (
                    item.canonical_name,
                    item.source_version,
                    item.target_version,
                    item.priority,
                    item.key,
                    str(item.migration_id),
                ),
            )
        )
        by_id: dict[MigrationId, MigrationDefinition] = {}
        by_key: dict[str, MigrationDefinition] = {}
        by_edge: dict[tuple[str, SemanticVersion, SemanticVersion], MigrationDefinition] = {}
        outgoing: dict[tuple[str, SemanticVersion], list[MigrationDefinition]] = {}
        incoming: dict[tuple[str, SemanticVersion], list[MigrationDefinition]] = {}
        for definition in ordered:
            edge = (
                definition.canonical_name,
                definition.source_version,
                definition.target_version,
            )
            if definition.migration_id in by_id:
                raise _error(
                    ErrorCode.DUPLICATE_MIGRATION_ID,
                    "Duplicate migration ID.",
                    str(definition.migration_id),
                )
            if definition.key in by_key:
                raise _error(
                    ErrorCode.DUPLICATE_MIGRATION_KEY,
                    "Duplicate migration key.",
                    definition.key,
                )
            if edge in by_edge:
                raise _error(
                    ErrorCode.DUPLICATE_MIGRATION_EDGE,
                    "Duplicate exact migration edge.",
                    f"{definition.canonical_name}:{definition.source_version}->{definition.target_version}",
                )
            source = contract_registry.get(definition.canonical_name, definition.source_version)
            target = contract_registry.get(definition.canonical_name, definition.target_version)
            if definition.status is MigrationStatus.ACTIVE and (source is None or target is None):
                raise _error(
                    ErrorCode.MIGRATION_ENDPOINT_NOT_FOUND,
                    "Active migration endpoint is absent from ContractRegistry.",
                    definition.key,
                )
            for registration, expected, label in (
                (source, definition.source_schema_fingerprint, "source"),
                (target, definition.target_schema_fingerprint, "target"),
            ):
                if registration is not None and expected is not None:
                    actual = generate_contract_schema(registration).schema_fingerprint
                    if expected != actual:
                        raise _error(
                            ErrorCode.MIGRATION_SCHEMA_FINGERPRINT_MISMATCH,
                            f"Migration {label} schema fingerprint is stale.",
                            definition.key,
                        )
            by_id[definition.migration_id] = definition
            by_key[definition.key] = definition
            by_edge[edge] = definition
            outgoing.setdefault((definition.canonical_name, definition.source_version), []).append(
                definition
            )
            incoming.setdefault((definition.canonical_name, definition.target_version), []).append(
                definition
            )
        for definition in ordered:
            if definition.reversible:
                reverse_migration_id = definition.reverse_migration_id
                if reverse_migration_id is None:
                    raise _error(
                        ErrorCode.MIGRATION_REVERSIBILITY_INVALID,
                        "Reversible migration requires a reverse migration ID.",
                        definition.key,
                    )
                reverse = by_id.get(reverse_migration_id)
                if (
                    reverse is None
                    or reverse.canonical_name != definition.canonical_name
                    or reverse.source_version != definition.target_version
                    or reverse.target_version != definition.source_version
                    or reverse.reverse_migration_id != definition.migration_id
                ):
                    raise _error(
                        ErrorCode.MIGRATION_REVERSIBILITY_INVALID,
                        "Reversible migration requires a reciprocal exact inverse edge.",
                        definition.key,
                    )
        object.__setattr__(self, "definitions", ordered)
        object.__setattr__(self, "contract_registry", contract_registry)
        object.__setattr__(self, "_by_id", MappingProxyType(by_id))
        object.__setattr__(self, "_by_key", MappingProxyType(by_key))
        object.__setattr__(self, "_by_edge", MappingProxyType(by_edge))
        object.__setattr__(
            self,
            "_outgoing",
            MappingProxyType({key: tuple(value) for key, value in outgoing.items()}),
        )
        object.__setattr__(
            self,
            "_incoming",
            MappingProxyType({key: tuple(value) for key, value in incoming.items()}),
        )
        semantic = tuple(
            {
                "identity": str(item.migration_id),
                "fingerprint": item.semantic_fingerprint(),
            }
            for item in ordered
        )
        object.__setattr__(
            self,
            "registry_fingerprint",
            compute_fingerprint(
                {
                    "contract_catalog_fingerprint": contract_registry.catalog_fingerprint,
                    "migrations": semantic,
                }
            ),
        )

    def get_by_id(self, migration_id: MigrationId) -> MigrationDefinition | None:
        return self._by_id.get(migration_id)

    def get_by_key(self, key: str) -> MigrationDefinition | None:
        return self._by_key.get(key)

    def get_edge(
        self,
        canonical_name: str,
        source_version: SemanticVersion,
        target_version: SemanticVersion,
    ) -> MigrationDefinition | None:
        return self._by_edge.get((canonical_name, source_version, target_version))

    def outgoing(
        self, canonical_name: str, version: SemanticVersion
    ) -> tuple[MigrationDefinition, ...]:
        return self._outgoing.get((canonical_name, version), ())

    def incoming(
        self, canonical_name: str, version: SemanticVersion
    ) -> tuple[MigrationDefinition, ...]:
        return self._incoming.get((canonical_name, version), ())

    def filter(
        self,
        *,
        canonical_name: str | None = None,
        direction: MigrationDirection | None = None,
        status: MigrationStatus | None = None,
        lossless: bool | None = None,
        reversible: bool | None = None,
    ) -> tuple[MigrationDefinition, ...]:
        return tuple(
            item
            for item in self.definitions
            if (canonical_name is None or item.canonical_name == canonical_name)
            and (direction is None or item.direction is direction)
            and (status is None or item.status is status)
            and (lossless is None or item.lossless is lossless)
            and (reversible is None or item.reversible is reversible)
        )


__all__ = ("MigrationRegistry",)
