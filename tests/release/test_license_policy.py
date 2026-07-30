"""Dependency license inventory policy tests."""

from __future__ import annotations

from scripts.check_release import parse_license_inventory
from scripts.release_common import evaluate_license_policy


def test_runtime_license_inventory_is_allowed() -> None:
    payload = """[
      {"Name": "pydantic", "Version": "2.13.4", "License": "MIT"},
      {"Name": "typing_extensions", "Version": "4.16.0", "License": "PSF-2.0"}
    ]"""
    policy = evaluate_license_policy(parse_license_inventory(payload))
    assert len(policy["allowed"]) == 2
    assert policy["denied"] == []
    assert policy["manual_review"] == []


def test_unknown_and_denied_licenses_fail_strict_classification() -> None:
    policy = evaluate_license_policy(
        [
            {"name": "unknown", "version": "1", "license": "UNKNOWN"},
            {"name": "copyleft", "version": "1", "license": "AGPL-3.0"},
        ]
    )
    assert [item["name"] for item in policy["manual_review"]] == ["unknown"]
    assert [item["name"] for item in policy["denied"]] == ["copyleft"]
