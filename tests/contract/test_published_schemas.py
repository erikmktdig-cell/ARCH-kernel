"""Validation of committed Draft 2020-12 schema artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from arch_kernel.contracts import ContractRegistryManifest
from arch_kernel.kernel import build_builtin_contract_registry

ROOT = Path(__file__).parents[2]
SCHEMAS = ROOT / "schemas"
FIXTURES = ROOT / "fixtures"


def _json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def test_committed_manifest_matches_builtin_registry() -> None:
    manifest = ContractRegistryManifest.model_validate_json(
        (SCHEMAS / "manifest.json").read_text(encoding="utf-8")
    )
    registry = build_builtin_contract_registry()
    assert manifest.catalog_fingerprint == registry.catalog_fingerprint
    assert manifest.descriptors == registry.descriptors


def test_every_committed_schema_is_valid_and_declared() -> None:
    manifest = ContractRegistryManifest.model_validate_json(
        (SCHEMAS / "manifest.json").read_text(encoding="utf-8")
    )
    declared = {descriptor.schema_filename for descriptor in manifest.descriptors}
    published = {
        path.relative_to(SCHEMAS).as_posix()
        for path in (SCHEMAS / "contracts").glob("*.schema.json")
    }
    assert published == declared
    for relative in sorted(declared):
        schema = _json(SCHEMAS / relative)
        Draft202012Validator.check_schema(schema)
        assert schema["$id"].startswith("https://schemas.arch.local/")


@pytest.mark.parametrize(
    ("canonical_name", "fixture"),
    [
        ("arch.project.project_state", "valid/minimal_project_state.json"),
        ("arch.event.event_envelope", "valid/event_envelope.json"),
        ("arch.patch.state_patch", "valid/state_patch/replace_project_profile.json"),
        (
            "arch.transition.transition_request",
            "valid/transitions/artifact_approval_request.json",
        ),
    ],
)
def test_representative_valid_fixtures_validate(
    canonical_name: str,
    fixture: str,
) -> None:
    registry = build_builtin_contract_registry()
    registration = registry.latest_active(canonical_name)
    assert registration is not None
    schema = _json(SCHEMAS / registration.descriptor.schema_filename)
    Draft202012Validator(schema).validate(_json(FIXTURES / fixture))


def test_structurally_invalid_event_fixture_fails_published_schema() -> None:
    registry = build_builtin_contract_registry()
    registration = registry.latest_active("arch.event.event_envelope")
    assert registration is not None
    schema = _json(SCHEMAS / registration.descriptor.schema_filename)
    invalid = _json(FIXTURES / "invalid/events/unknown_field.json")
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(invalid)
