"""Reusable fixture catalog checks for WP-K08."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from arch_kernel.contracts import ValidationIntent

FIXTURES = Path(__file__).parents[2] / "fixtures"


def _load(relative: str) -> list[dict[str, str]]:
    payload = json.loads((FIXTURES / relative).read_text(encoding="utf-8"))
    return cast(list[dict[str, str]], payload["cases"])


def test_valid_catalog_has_required_reusable_scenarios() -> None:
    cases = _load("valid/validation_pipeline/cases.json")
    assert len(cases) >= 7
    assert len({case["name"] for case in cases}) == len(cases)
    assert {case["intent"] for case in cases} == {intent.value for intent in ValidationIntent}
    for case in cases:
        for field, value in case.items():
            if field.endswith("_fixture"):
                assert (FIXTURES / value).is_file()


def test_invalid_catalog_has_required_fail_closed_scenarios() -> None:
    cases = _load("invalid/validation_pipeline/cases.json")
    assert len(cases) >= 13
    assert len({case["name"] for case in cases}) == len(cases)
    assert all(case["expected_code"] for case in cases)
