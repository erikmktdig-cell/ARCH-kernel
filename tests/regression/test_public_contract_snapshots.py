"""Readable public-surface regression snapshots."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, cast

from scripts.build_regression_snapshots import (
    coverage_inventory_snapshot,
    public_contract_snapshot,
)

SNAPSHOTS = Path(__file__).parent / "snapshots"


def _load(name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((SNAPSHOTS / name).read_text(encoding="utf-8")),
    )


def test_public_contract_surface_matches_intentional_snapshot() -> None:
    assert public_contract_snapshot() == _load("public_contracts.json")


def test_coverage_inventory_matches_all_production_modules_and_codes() -> None:
    assert coverage_inventory_snapshot() == _load("coverage_inventory.json")


def test_every_production_module_is_importable_from_inventory() -> None:
    inventory = _load("coverage_inventory.json")
    for module_name in inventory["production_modules"]:
        assert importlib.import_module(module_name).__name__ == module_name
