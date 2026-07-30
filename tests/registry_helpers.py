"""Deterministic builders for WP-K09 registry and compatibility tests."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from arch_kernel.contracts import (
    ContractAlias,
    ContractDescriptor,
    ContractKind,
    ContractRegistration,
    ContractStatus,
    SchemaArtifact,
    SemanticVersion,
)
from arch_kernel.kernel.fingerprints import compute_fingerprint
from arch_kernel.kernel.schema_generation import (
    generate_contract_schema,
    normalize_json_schema,
)

ZERO_FINGERPRINT = "sha256:" + ("0" * 64)
VERSION = SemanticVersion.parse("1.0.0")


class CatalogModelV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str


class CatalogModelV2(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    note: str | None = None


class CatalogModelV2Breaking(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    count: int


def registration(
    model: type[BaseModel] = CatalogModelV1,
    *,
    canonical_name: str = "arch.test.catalog_model",
    version: str = "1.0.0",
    aliases: tuple[ContractAlias, ...] = (),
    status: ContractStatus = ContractStatus.ACTIVE,
    kind: ContractKind = ContractKind.RECORD,
) -> ContractRegistration:
    semantic_version = SemanticVersion.parse(version)
    descriptor = ContractDescriptor(
        canonical_name=canonical_name,
        version=semantic_version,
        kind=kind,
        status=status,
        python_module=model.__module__,
        python_qualname=model.__qualname__,
        schema_id=f"https://schemas.arch.local/{canonical_name}/{semantic_version}",
        schema_filename=f"contracts/{canonical_name}.{semantic_version}.schema.json",
        title=model.__name__,
        description="Reusable test contract.",
        aliases=aliases,
        tags=("test",),
        model_fingerprint=compute_fingerprint(
            {"module": model.__module__, "qualname": model.__qualname__}
        ),
        schema_fingerprint=ZERO_FINGERPRINT,
        descriptor_version=VERSION,
    )
    provisional = ContractRegistration(descriptor, model)
    artifact = generate_contract_schema(provisional)
    return ContractRegistration(
        descriptor.model_copy(update={"schema_fingerprint": artifact.schema_fingerprint}),
        model,
    )


def schema_artifact(
    schema: dict[str, Any],
    *,
    version: str = "1.0.0",
    canonical_name: str = "arch.test.compatibility_model",
) -> SchemaArtifact:
    normalized = normalize_json_schema(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://schemas.arch.local/{canonical_name}/{version}",
            "title": "CompatibilityModel",
            **schema,
        }
    )
    assert isinstance(normalized, dict)
    return SchemaArtifact.model_validate(
        {
            "canonical_name": canonical_name,
            "version": version,
            "schema_id": f"https://schemas.arch.local/{canonical_name}/{version}",
            "normalized_schema": normalized,
            "schema_fingerprint": compute_fingerprint(normalized),
            "filename": f"contracts/{canonical_name}.{version}.schema.json",
        }
    )


__all__ = (
    "VERSION",
    "CatalogModelV1",
    "CatalogModelV2",
    "CatalogModelV2Breaking",
    "registration",
    "schema_artifact",
)
