"""Contract model tests for WP-K09."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import (
    CompatibilityLevel,
    ContractAlias,
    ContractKind,
    ContractRegistration,
    ContractStatus,
    VersionBump,
    validate_canonical_contract_name,
)
from arch_kernel.kernel import (
    ContractRegistry,
    audit_contract_registry,
    build_builtin_contract_registry,
    build_registry_manifest,
    compare_schema_artifacts,
    generate_contract_schema,
    generate_registry_schemas,
    publish_registry_schemas,
    recommend_version_bump,
)
from tests.registry_helpers import VERSION, CatalogModelV1, registration


def test_registry_enums_are_closed_and_canonical() -> None:
    assert len(ContractKind) == 9
    assert tuple(item.value for item in ContractStatus) == (
        "active",
        "deprecated",
        "reserved",
        "internal",
    )
    assert len(CompatibilityLevel) == 6
    assert tuple(item.value for item in VersionBump) == (
        "patch",
        "minor",
        "major",
        "manual_review",
    )


@pytest.mark.parametrize(
    "value",
    [
        "project.state",
        "arch.Project.state",
        "arch.project.",
        "arch..state",
        "arch.project.state-name",
        " arch.project.state",
    ],
)
def test_canonical_name_rejects_malformed_values(value: str) -> None:
    with pytest.raises(ValueError, match="arch"):
        validate_canonical_contract_name(value)


def test_alias_lifecycle_is_ordered_and_frozen() -> None:
    alias = ContractAlias(
        alias="arch.legacy.catalog_model",
        deprecated_since=VERSION,
        removal_version=type(VERSION).parse("2.0.0"),
        note="Use the canonical name.",
    )
    with pytest.raises(ValidationError, match="frozen"):
        alias.note = "changed"
    with pytest.raises(ValidationError, match="greater"):
        ContractAlias(
            alias="arch.legacy.catalog_model",
            deprecated_since=type(VERSION).parse("2.0.0"),
            removal_version=VERSION,
        )


def test_descriptor_derivations_and_aliases_are_validated() -> None:
    descriptor = registration().descriptor
    with pytest.raises(ValidationError, match="derive"):
        type(descriptor).model_validate(
            {
                **descriptor.model_dump(),
                "schema_id": "https://schemas.arch.local/arch.test.other/1.0.0",
            }
        )
    with pytest.raises(ValidationError, match="cannot equal"):
        type(descriptor).model_validate(
            {
                **descriptor.model_dump(),
                "aliases": ({"alias": descriptor.canonical_name},),
            }
        )


def test_registration_requires_pydantic_model_and_is_runtime_only() -> None:
    descriptor = registration().descriptor
    with pytest.raises(TypeError, match="Pydantic"):
        ContractRegistration(descriptor, str)  # type: ignore[arg-type]
    valid = ContractRegistration(descriptor, CatalogModelV1)
    assert not hasattr(valid, "model_dump")


def test_k09_public_exports_are_available() -> None:
    assert ContractRegistry.__name__ == "ContractRegistry"
    assert callable(build_builtin_contract_registry)
    assert callable(generate_contract_schema)
    assert callable(generate_registry_schemas)
    assert callable(build_registry_manifest)
    assert callable(publish_registry_schemas)
    assert callable(compare_schema_artifacts)
    assert callable(recommend_version_bump)
    assert callable(audit_contract_registry)
