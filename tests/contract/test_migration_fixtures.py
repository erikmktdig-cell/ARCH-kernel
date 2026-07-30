"""Contract checks for the WP-K10 migration fixture catalogs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from arch_kernel.kernel.errors import ErrorCode

ROOT = Path(__file__).parents[2] / "fixtures"


def _catalog(kind: str) -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads((ROOT / kind / "migrations" / "cases.json").read_text()),
    )


def test_valid_migration_fixture_catalog_has_required_scenarios() -> None:
    catalog = _catalog("valid")
    cases = catalog["cases"]

    assert isinstance(cases, list)
    assert len(cases) >= 9
    assert len({item["name"] for item in cases}) == len(cases)
    assert {item["expect"] for item in cases} <= {"succeeded", "not_required"}


def test_invalid_migration_fixture_catalog_has_required_scenarios() -> None:
    catalog = _catalog("invalid")
    cases = catalog["cases"]
    known_codes = {item.value for item in ErrorCode}

    assert isinstance(cases, list)
    assert len(cases) >= 25
    assert len({item["name"] for item in cases}) == len(cases)
    assert {item["error"] for item in cases} <= known_codes
