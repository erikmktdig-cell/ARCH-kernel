"""Deterministic Pydantic JSON Schema generation and local publication."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from pydantic import PydanticInvalidForJsonSchema

from arch_kernel.contracts.registry import (
    ContractRegistration,
    ContractRegistryManifest,
)
from arch_kernel.contracts.schema import SchemaArtifact
from arch_kernel.contracts.versions import SemanticVersion
from arch_kernel.kernel.errors import ArchKernelError, ErrorCode, ErrorDetail, Severity
from arch_kernel.kernel.event_validation import freeze_json_object
from arch_kernel.kernel.fingerprints import compute_fingerprint

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
GENERATOR_IDENTITY = "arch-kernel.pydantic-json-schema"
GENERATOR_VERSION = SemanticVersion.parse("1.0.0")
REGISTRY_FORMAT_VERSION = SemanticVersion.parse("1.0.0")

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


def normalize_json_schema(value: object) -> JsonValue:
    """Recursively sort mappings while preserving every array's semantic order."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): normalize_json_schema(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [normalize_json_schema(item) for item in value]
    raise TypeError(f"Schema value {type(value).__name__} is not JSON-compatible.")


def _schema_error(registration: ContractRegistration, error: Exception) -> ArchKernelError:
    return ArchKernelError(
        ErrorDetail(
            code=ErrorCode.SCHEMA_GENERATION_FAILED,
            message="Pydantic JSON Schema generation failed.",
            path=("schema",),
            entity_type="contract",
            entity_id=registration.descriptor.canonical_name,
            actual=type(error).__name__,
            remediation_hint="Use a supported public Pydantic contract model.",
            severity=Severity.ERROR,
        )
    )


def generate_contract_schema(registration: ContractRegistration) -> SchemaArtifact:
    """Generate and normalize one Draft 2020-12 publication artifact."""

    descriptor = registration.descriptor
    try:
        generated = registration.model.model_json_schema(
            by_alias=False,
            mode="validation",
        )
    except (PydanticInvalidForJsonSchema, TypeError, ValueError) as error:
        raise _schema_error(registration, error) from error
    generated["$schema"] = SCHEMA_DIALECT
    generated["$id"] = descriptor.schema_id
    generated["title"] = descriptor.title or descriptor.python_qualname.rsplit(".", 1)[-1]
    normalized = normalize_json_schema(generated)
    if not isinstance(normalized, dict):  # pragma: no cover - Pydantic always emits an object
        raise _schema_error(registration, TypeError("root schema is not an object"))
    fingerprint = compute_fingerprint(normalized)
    return SchemaArtifact(
        canonical_name=descriptor.canonical_name,
        version=descriptor.version,
        schema_id=descriptor.schema_id,
        normalized_schema=freeze_json_object(normalized),
        schema_fingerprint=fingerprint,
        filename=descriptor.schema_filename,
    )


def generate_registry_schemas(
    registry: Any,
) -> tuple[SchemaArtifact, ...]:
    """Purely generate artifacts in canonical registry order."""

    return tuple(generate_contract_schema(item) for item in registry.registrations)


def build_registry_manifest(registry: Any) -> ContractRegistryManifest:
    """Build the semantic manifest without filesystem metadata."""

    return ContractRegistryManifest(
        registry_format_version=REGISTRY_FORMAT_VERSION,
        descriptors=registry.descriptors,
        catalog_fingerprint=registry.catalog_fingerprint,
        schema_dialect=SCHEMA_DIALECT,
        generator_identity=GENERATOR_IDENTITY,
        generator_version=GENERATOR_VERSION,
    )


def _pretty_json(value: object) -> bytes:
    normalized = normalize_json_schema(value)
    return (
        json.dumps(
            normalized,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def publish_registry_schemas(
    registry: Any,
    output_dir: Path,
) -> ContractRegistryManifest:
    """Idempotently publish deterministic schemas, then the manifest."""

    if not isinstance(output_dir, Path):
        raise TypeError("output_dir must be a pathlib.Path.")
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        for artifact in generate_registry_schemas(registry):
            target = output_dir / Path(artifact.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_pretty_json(artifact.normalized_schema))
        manifest = build_registry_manifest(registry)
        (output_dir / "manifest.json").write_bytes(_pretty_json(manifest.model_dump(mode="json")))
        return manifest
    except OSError as error:
        raise ArchKernelError(
            ErrorDetail(
                code=ErrorCode.SCHEMA_PUBLICATION_FAILED,
                message="Contract schema publication failed.",
                path=("output_dir",),
                entity_type="contract_registry",
                actual=type(error).__name__,
                severity=Severity.ERROR,
            )
        ) from error


def schema_as_dict(artifact: SchemaArtifact) -> dict[str, Any]:
    """Return a conventional detached JSON Schema mapping."""

    return cast(dict[str, Any], artifact.model_dump(mode="json")["normalized_schema"])


__all__ = (
    "GENERATOR_IDENTITY",
    "GENERATOR_VERSION",
    "REGISTRY_FORMAT_VERSION",
    "SCHEMA_DIALECT",
    "build_registry_manifest",
    "generate_contract_schema",
    "generate_registry_schemas",
    "normalize_json_schema",
    "publish_registry_schemas",
    "schema_as_dict",
)
