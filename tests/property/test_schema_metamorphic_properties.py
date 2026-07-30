"""Metamorphic properties for K09 schema generation and comparison."""

from __future__ import annotations

import json

from arch_kernel.contracts import CompatibilityLevel
from arch_kernel.kernel import compare_schema_artifacts
from arch_kernel.kernel.fingerprints import compute_fingerprint
from arch_kernel.kernel.schema_generation import normalize_json_schema
from tests.registry_helpers import schema_artifact


def test_schema_normalization_is_idempotent_and_format_independent() -> None:
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    normalized = normalize_json_schema(schema)
    pretty = json.loads(json.dumps(schema, indent=4))

    assert normalize_json_schema(normalized) == normalized
    assert compute_fingerprint(normalized) == compute_fingerprint(normalize_json_schema(pretty))


def test_required_property_and_enum_contraction_remain_breaking() -> None:
    source = schema_artifact(
        {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["a", "b"]}},
            "required": [],
        }
    )
    target = schema_artifact(
        {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["a"]}},
            "required": ["status"],
        },
        version="2.0.0",
    )

    assert compare_schema_artifacts(source, target).level is CompatibilityLevel.BREAKING
