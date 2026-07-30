"""Property tests for deterministic WP-K09 registry behavior."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given, settings
from hypothesis import strategies as st

from arch_kernel.contracts import CompatibilityLevel, VersionBump
from arch_kernel.kernel.contract_registry import ContractRegistry
from arch_kernel.kernel.fingerprints import compute_fingerprint
from arch_kernel.kernel.schema_compatibility import compare_schema_artifacts
from arch_kernel.kernel.schema_generation import (
    normalize_json_schema,
    publish_registry_schemas,
)
from tests.registry_helpers import (
    CatalogModelV2,
    registration,
    schema_artifact,
)


@given(st.booleans())
def test_registry_insertion_order_never_changes_fingerprints(reverse: bool) -> None:
    first = registration()
    second = registration(CatalogModelV2, canonical_name="arch.test.second_model")
    values = (second, first) if reverse else (first, second)
    candidate = ContractRegistry(values)
    canonical = ContractRegistry((first, second))
    assert candidate.registrations == canonical.registrations
    assert candidate.catalog_fingerprint == canonical.catalog_fingerprint


@given(st.permutations(("alpha", "beta", "gamma", "delta")))
def test_mapping_insertion_order_never_changes_schema_fingerprint(
    keys: list[str],
) -> None:
    candidate = {key: {"type": "string"} for key in keys}
    baseline = {key: {"type": "string"} for key in sorted(keys)}
    assert compute_fingerprint(normalize_json_schema(candidate)) == compute_fingerprint(
        normalize_json_schema(baseline)
    )


@given(st.integers(min_value=0, max_value=100))
def test_equivalent_schemas_have_identical_reports(value: int) -> None:
    schema = {"type": "integer", "minimum": value}
    source = schema_artifact(schema)
    target = schema_artifact(dict(reversed(tuple(schema.items()))), version="1.0.1")
    report = compare_schema_artifacts(source, target)
    assert report.level is CompatibilityLevel.IDENTICAL
    assert report.minimum_version_bump is VersionBump.PATCH


@given(st.from_regex(r"[a-z][a-z0-9_]{0,12}", fullmatch=True))
def test_adding_required_property_is_always_breaking(name: str) -> None:
    source_schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    target_schema = {
        **source_schema,
        "properties": {name: {"type": "string"}},
        "required": [name],
    }
    report = compare_schema_artifacts(
        schema_artifact(source_schema),
        schema_artifact(target_schema, version="2.0.0"),
    )
    assert report.level is CompatibilityLevel.BREAKING


@given(
    st.lists(
        st.from_regex(r"[a-z][a-z0-9]{0,8}", fullmatch=True),
        min_size=2,
        max_size=8,
        unique=True,
    )
)
def test_removing_enum_value_is_always_breaking(values: list[str]) -> None:
    report = compare_schema_artifacts(
        schema_artifact({"type": "string", "enum": values}),
        schema_artifact(
            {"type": "string", "enum": values[:-1]},
            version="2.0.0",
        ),
    )
    assert report.level is CompatibilityLevel.BREAKING


@settings(max_examples=3, deadline=None)
@given(st.booleans())
def test_repeated_publication_is_byte_identical(reverse: bool) -> None:
    item = registration()
    registry = ContractRegistry(tuple(reversed((item,))) if reverse else (item,))
    with TemporaryDirectory(dir=Path.cwd()) as temporary:
        output = Path(temporary)
        first = publish_registry_schemas(registry, output)
        first_bytes = {
            path.relative_to(output).as_posix(): path.read_bytes()
            for path in output.rglob("*.json")
        }
        second = publish_registry_schemas(registry, output)
        second_bytes = {
            path.relative_to(output).as_posix(): path.read_bytes()
            for path in output.rglob("*.json")
        }
    assert first == second
    assert first_bytes == second_bytes
