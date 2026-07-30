"""Schema generation and deterministic publication tests for WP-K09."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from arch_kernel.contracts import ContractRegistryManifest
from arch_kernel.kernel import (
    build_builtin_contract_registry,
    build_registry_manifest,
    generate_contract_schema,
    generate_registry_schemas,
    publish_registry_schemas,
)
from arch_kernel.kernel.schema_generation import normalize_json_schema


def test_every_builtin_schema_is_valid_draft_2020_12() -> None:
    registry = build_builtin_contract_registry()
    artifacts = generate_registry_schemas(registry)
    assert len(artifacts) == len(registry.registrations)
    for artifact in artifacts:
        schema = artifact.model_dump(mode="json")["normalized_schema"]
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"] == artifact.schema_id
        assert "\\" not in artifact.filename


def test_schema_generation_is_stable_and_normalization_sorts_only_mappings() -> None:
    registration = build_builtin_contract_registry().registrations[0]
    first = generate_contract_schema(registration)
    second = generate_contract_schema(registration)
    assert first == second
    assert normalize_json_schema({"b": 1, "a": {"z": 2, "y": 1}, "enum": ["b", "a"]}) == {
        "a": {"y": 1, "z": 2},
        "b": 1,
        "enum": ["b", "a"],
    }


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*.json"))
    }


def test_publication_is_idempotent_and_preserves_unrelated_files() -> None:
    registry = build_builtin_contract_registry()
    with TemporaryDirectory(dir=Path.cwd()) as temporary:
        output = Path(temporary)
        unrelated = output / "keep.txt"
        unrelated.write_text("keep", encoding="utf-8")
        first_manifest = publish_registry_schemas(registry, output)
        first = _files(output)
        second_manifest = publish_registry_schemas(registry, output)
        second = _files(output)
        assert first == second
        assert first_manifest == second_manifest
        assert unrelated.read_text(encoding="utf-8") == "keep"
        assert first["manifest.json"].endswith(b"\n")
        assert all(b"C:\\\\" not in content for content in first.values())


def test_manifest_round_trip_and_semantic_fingerprint() -> None:
    registry = build_builtin_contract_registry()
    manifest = build_registry_manifest(registry)
    rebuilt = type(manifest).model_validate_json(manifest.model_dump_json())
    assert rebuilt == manifest
    assert manifest.catalog_fingerprint == registry.catalog_fingerprint
    assert manifest.semantic_fingerprint() == rebuilt.semantic_fingerprint()


def test_manifest_rejects_fingerprint_mismatch() -> None:
    manifest = build_registry_manifest(build_builtin_contract_registry())
    payload = manifest.model_dump(mode="json")
    payload["catalog_fingerprint"] = "sha256:" + ("0" * 64)
    with pytest.raises(ValidationError, match="ordered descriptors"):
        ContractRegistryManifest.model_validate_json(json.dumps(payload))
