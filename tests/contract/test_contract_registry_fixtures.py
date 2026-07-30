"""Fixture catalog tests for WP-K09."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from arch_kernel.contracts import ContractRegistryManifest

FIXTURES = Path(__file__).parents[2] / "fixtures"


def _json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def test_valid_registry_fixtures_cover_required_scenarios() -> None:
    root = FIXTURES / "valid" / "contract_registry"
    expected = {
        "descriptor_with_alias.json",
        "compatible_versions.json",
        "breaking_major.json",
        "canonical_schema_artifact.json",
        "minimal_manifest.json",
        "builtin_manifest.json",
    }
    assert expected <= {path.name for path in root.glob("*.json")}
    for filename in expected - {"minimal_manifest.json", "builtin_manifest.json"}:
        assert _json(root / filename)
    for filename in ("minimal_manifest.json", "builtin_manifest.json"):
        ContractRegistryManifest.model_validate_json((root / filename).read_text(encoding="utf-8"))


def test_invalid_registry_fixture_catalog_has_independent_cases() -> None:
    payload = _json(FIXTURES / "invalid" / "contract_registry" / "cases.json")
    cases = payload["cases"]
    assert len(cases) >= 14
    assert len({case["name"] for case in cases}) == len(cases)
    assert all(case["expected_code"] for case in cases)
