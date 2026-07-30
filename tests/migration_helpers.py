"""Reusable deterministic builders for WP-K10 migration tests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from arch_kernel.contracts import (
    MigrationDefinition,
    MigrationDirection,
    MigrationId,
    MigrationOperation,
    MigrationOperationType,
    MigrationPolicy,
    MigrationRequest,
    MigrationStatus,
    SemanticVersion,
)
from arch_kernel.kernel.contract_registry import ContractRegistry
from arch_kernel.kernel.event_validation import freeze_json_object
from arch_kernel.kernel.migration_registry import MigrationRegistry
from tests.registry_helpers import registration

CANONICAL_NAME = "arch.test.migration_payload"
EVALUATED_AT = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
MIGRATION_IDS = tuple(
    MigrationId.from_str(value)
    for value in (
        "MIG-01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "MIG-01ARZ3NDEKTSV4RRFFQ69G5FAW",
        "MIG-01ARZ3NDEKTSV4RRFFQ69G5FAX",
        "MIG-01ARZ3NDEKTSV4RRFFQ69G5FAY",
        "MIG-01ARZ3NDEKTSV4RRFFQ69G5FAZ",
        "MIG-01ARZ3NDEKTSV4RRFFQ69G5FB0",
        "MIG-01ARZ3NDEKTSV4RRFFQ69G5FB1",
        "MIG-01ARZ3NDEKTSV4RRFFQ69G5FB2",
    )
)


class PayloadV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str


class PayloadV2(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    note: str | None = None


class PayloadV3(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    note: str | None = None
    label: str | None = None


class PayloadV4(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    note: str | None = None
    label: str | None = None
    enabled: bool = True


class OperationsSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    old_name: str
    status: str
    count: str
    source: str
    movable: str
    replaceable: str


class OperationsTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    status: str
    count: int
    copied: str
    moved: str
    replaceable: str
    defaulted: bool
    added: str


def contract_registry(
    *models_and_versions: tuple[type[BaseModel], str],
    canonical_name: str = CANONICAL_NAME,
) -> ContractRegistry:
    return ContractRegistry(
        tuple(
            registration(
                model,
                canonical_name=canonical_name,
                version=version,
            )
            for model, version in models_and_versions
        )
    )


def operation(
    operation_type: MigrationOperationType,
    path: str,
    **values: object,
) -> MigrationOperation:
    return MigrationOperation.model_validate(
        {"operation_type": operation_type, "path": path, **values}
    )


def definition(
    *,
    index: int = 0,
    source: str = "1.0.0",
    target: str = "1.1.0",
    operations: tuple[MigrationOperation, ...] | None = None,
    canonical_name: str = CANONICAL_NAME,
    status: MigrationStatus = MigrationStatus.ACTIVE,
    lossless: bool = True,
    reversible: bool = False,
    reverse_index: int | None = None,
    identity: bool = False,
    priority: int = 0,
) -> MigrationDefinition:
    source_version = SemanticVersion.parse(source)
    target_version = SemanticVersion.parse(target)
    direction = (
        MigrationDirection.UPGRADE
        if target_version > source_version
        else MigrationDirection.DOWNGRADE
    )
    if operations is None:
        operations = (
            operation(
                MigrationOperationType.SET_DEFAULT,
                "/note",
                value=None,
            ),
        )
    return MigrationDefinition(
        migration_id=MIGRATION_IDS[index],
        key=f"migration.case_{index}",
        title=f"Migration case {index}",
        description="Deterministic migration test definition.",
        canonical_name=canonical_name,
        source_version=source_version,
        target_version=target_version,
        direction=direction,
        status=status,
        priority=priority,
        operations=operations,
        identity=identity,
        lossless=lossless,
        reversible=reversible,
        reverse_migration_id=(MIGRATION_IDS[reverse_index] if reverse_index is not None else None),
        contract_version=SemanticVersion.parse("1.0.0"),
        schema_uri="https://schemas.arch.local/arch.kernel/migration-definition/1.0.0",
    )


def migration_registry(
    definitions: tuple[MigrationDefinition, ...],
    contracts: ContractRegistry,
) -> MigrationRegistry:
    return MigrationRegistry(definitions, contracts)


def request(
    payload: Mapping[str, object],
    *,
    source: str = "1.0.0",
    target: str = "1.1.0",
    canonical_name: str = CANONICAL_NAME,
    policy: MigrationPolicy | None = None,
) -> MigrationRequest:
    return MigrationRequest(
        canonical_name=canonical_name,
        source_version=SemanticVersion.parse(source),
        target_version=SemanticVersion.parse(target),
        source_payload=freeze_json_object(dict(payload)),
        evaluated_at=EVALUATED_AT,
        policy=policy or MigrationPolicy(),
    )


__all__ = (
    "CANONICAL_NAME",
    "EVALUATED_AT",
    "MIGRATION_IDS",
    "OperationsSource",
    "OperationsTarget",
    "PayloadV1",
    "PayloadV2",
    "PayloadV3",
    "PayloadV4",
    "contract_registry",
    "definition",
    "migration_registry",
    "operation",
    "request",
)
