"""Conservative compatibility and version audit tests for WP-K09."""

from __future__ import annotations

from typing import Any

import pytest

from arch_kernel.contracts import (
    CompatibilityLevel,
    VersionBump,
)
from arch_kernel.kernel import ErrorCode
from arch_kernel.kernel.contract_registry import ContractRegistry
from arch_kernel.kernel.schema_compatibility import (
    audit_contract_registry,
    compare_schema_artifacts,
    recommend_version_bump,
)
from tests.registry_helpers import (
    CatalogModelV1,
    CatalogModelV2Breaking,
    registration,
    schema_artifact,
)

OBJECT: dict[str, Any] = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
    "additionalProperties": False,
}


def test_identical_schema_is_patch_compatible_and_stable() -> None:
    source = schema_artifact(OBJECT)
    target = schema_artifact(OBJECT, version="1.0.1")
    first = compare_schema_artifacts(source, target)
    second = compare_schema_artifacts(source, target)
    assert first.level is CompatibilityLevel.IDENTICAL
    assert first.minimum_version_bump is VersionBump.PATCH
    assert first.report_fingerprint == second.report_fingerprint


def test_required_property_addition_and_enum_contraction_are_breaking() -> None:
    required = {
        **OBJECT,
        "properties": {
            **OBJECT["properties"],
            "count": {"type": "integer"},
        },
        "required": ["name", "count"],
    }
    report = compare_schema_artifacts(
        schema_artifact(OBJECT),
        schema_artifact(required, version="2.0.0"),
    )
    assert report.level is CompatibilityLevel.BREAKING
    assert report.minimum_version_bump is VersionBump.MAJOR
    assert "REQUIRED_PROPERTY_ADDED" in {item.code for item in report.findings}

    old_enum = schema_artifact({"type": "string", "enum": ["a", "b"]})
    new_enum = schema_artifact(
        {"type": "string", "enum": ["a"]},
        version="2.0.0",
    )
    assert compare_schema_artifacts(old_enum, new_enum).level is CompatibilityLevel.BREAKING


def test_enum_expansion_and_constraint_relaxation_are_directional() -> None:
    expanded = compare_schema_artifacts(
        schema_artifact({"type": "string", "enum": ["a"]}),
        schema_artifact(
            {"type": "string", "enum": ["a", "b"]},
            version="1.1.0",
        ),
    )
    assert expanded.level is CompatibilityLevel.BACKWARD_COMPATIBLE
    assert expanded.backward_compatible
    assert not expanded.forward_compatible
    relaxed = compare_schema_artifacts(
        schema_artifact({"type": "string", "minLength": 3}),
        schema_artifact({"type": "string", "minLength": 1}, version="1.1.0"),
    )
    assert relaxed.level is CompatibilityLevel.BACKWARD_COMPATIBLE


def test_unsupported_changed_construct_is_unknown() -> None:
    report = compare_schema_artifacts(
        schema_artifact({"type": "string", "pattern": "^a"}),
        schema_artifact({"type": "string", "pattern": "^b"}, version="2.0.0"),
    )
    assert report.level is CompatibilityLevel.UNKNOWN
    assert report.minimum_version_bump is VersionBump.MANUAL_REVIEW
    assert report.findings[0].code == ErrorCode.SCHEMA_COMPATIBILITY_UNKNOWN.value


def test_type_required_and_property_changes_cover_both_directions() -> None:
    widened_type = compare_schema_artifacts(
        schema_artifact({"type": "string"}),
        schema_artifact({"type": ["string", "null"]}, version="1.1.0"),
    )
    assert widened_type.level is CompatibilityLevel.BACKWARD_COMPATIBLE
    narrowed_type = compare_schema_artifacts(
        schema_artifact({"type": ["string", "null"]}),
        schema_artifact({"type": "string"}, version="2.0.0"),
    )
    assert narrowed_type.level is CompatibilityLevel.BREAKING
    changed_type = compare_schema_artifacts(
        schema_artifact({"type": "string"}),
        schema_artifact({"type": "integer"}, version="2.0.0"),
    )
    assert changed_type.level is CompatibilityLevel.BREAKING

    optional = {
        **OBJECT,
        "required": [],
    }
    required_removed = compare_schema_artifacts(
        schema_artifact(OBJECT),
        schema_artifact(optional, version="1.1.0"),
    )
    assert required_removed.level is CompatibilityLevel.BACKWARD_COMPATIBLE

    property_removed = compare_schema_artifacts(
        schema_artifact(OBJECT),
        schema_artifact(
            {"type": "object", "properties": {}, "additionalProperties": False},
            version="2.0.0",
        ),
    )
    assert property_removed.level is CompatibilityLevel.BREAKING


def test_bounds_additional_properties_arrays_and_unions_are_directional() -> None:
    tightened = compare_schema_artifacts(
        schema_artifact({"type": "number", "maximum": 10}),
        schema_artifact({"type": "number", "maximum": 5}, version="2.0.0"),
    )
    assert tightened.level is CompatibilityLevel.BREAKING
    removed_bound = compare_schema_artifacts(
        schema_artifact({"type": "string", "maxLength": 5}),
        schema_artifact({"type": "string"}, version="1.1.0"),
    )
    assert removed_bound.level is CompatibilityLevel.BACKWARD_COMPATIBLE

    closed = compare_schema_artifacts(
        schema_artifact({"type": "object", "additionalProperties": True}),
        schema_artifact(
            {"type": "object", "additionalProperties": False},
            version="2.0.0",
        ),
    )
    assert closed.level is CompatibilityLevel.BREAKING
    opened = compare_schema_artifacts(
        schema_artifact({"type": "object", "additionalProperties": False}),
        schema_artifact(
            {"type": "object", "additionalProperties": True},
            version="1.1.0",
        ),
    )
    assert opened.level is CompatibilityLevel.BACKWARD_COMPATIBLE

    array_change = compare_schema_artifacts(
        schema_artifact({"type": "array", "items": {"type": "string"}}),
        schema_artifact(
            {"type": "array", "items": {"type": ["string", "null"]}},
            version="1.1.0",
        ),
    )
    assert array_change.level is CompatibilityLevel.BACKWARD_COMPATIBLE
    unknown_array = compare_schema_artifacts(
        schema_artifact({"type": "array", "items": True}),
        schema_artifact({"type": "array", "items": False}, version="2.0.0"),
    )
    assert unknown_array.level is CompatibilityLevel.UNKNOWN

    union_added = compare_schema_artifacts(
        schema_artifact({"oneOf": [{"type": "string"}]}),
        schema_artifact(
            {"oneOf": [{"type": "string"}, {"type": "integer"}]},
            version="1.1.0",
        ),
    )
    assert union_added.level is CompatibilityLevel.BACKWARD_COMPATIBLE
    union_removed = compare_schema_artifacts(
        schema_artifact({"anyOf": [{"type": "string"}, {"type": "integer"}]}),
        schema_artifact({"anyOf": [{"type": "string"}]}, version="2.0.0"),
    )
    assert union_removed.level is CompatibilityLevel.BREAKING


def test_comparison_requires_same_identity() -> None:
    with pytest.raises(ValueError, match="same canonical"):
        compare_schema_artifacts(
            schema_artifact(OBJECT),
            schema_artifact(
                OBJECT,
                canonical_name="arch.test.other_model",
                version="1.0.1",
            ),
        )


def test_registry_audit_rejects_minor_breaking_change_and_accepts_major() -> None:
    source = registration(CatalogModelV1)
    minor = registration(CatalogModelV2Breaking, version="1.1.0")
    minor_audit = audit_contract_registry(ContractRegistry((source, minor)))
    assert not minor_audit.success
    assert minor_audit.findings[0].code == ErrorCode.INADEQUATE_VERSION_BUMP.value

    major = registration(CatalogModelV2Breaking, version="2.0.0")
    major_audit = audit_contract_registry(ContractRegistry((source, major)))
    assert major_audit.success
    assert major_audit.audited_version_pair_count == 1


@pytest.mark.parametrize(
    ("level", "bump"),
    [
        (CompatibilityLevel.IDENTICAL, VersionBump.PATCH),
        (CompatibilityLevel.FULLY_COMPATIBLE, VersionBump.MINOR),
        (CompatibilityLevel.BACKWARD_COMPATIBLE, VersionBump.MINOR),
        (CompatibilityLevel.FORWARD_COMPATIBLE, VersionBump.MINOR),
        (CompatibilityLevel.BREAKING, VersionBump.MAJOR),
        (CompatibilityLevel.UNKNOWN, VersionBump.MANUAL_REVIEW),
    ],
)
def test_version_bump_recommendation(
    level: CompatibilityLevel,
    bump: VersionBump,
) -> None:
    assert recommend_version_bump(level) is bump
