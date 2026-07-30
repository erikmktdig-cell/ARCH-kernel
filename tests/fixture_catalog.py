"""Detached deterministic fixture loading for WP-K11 tests."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from arch_kernel.kernel.fingerprints import compute_fingerprint

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "fixtures"
MANIFEST = FIXTURES / "manifest.json"
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$", re.ASCII)
FIXTURE_CLASSES = frozenset(
    {
        "valid",
        "invalid_contract",
        "invalid_aggregate",
        "rejected_policy",
        "non_blocking_finding",
        "migration_success",
        "migration_failure",
        "regression",
    }
)
type FixturePayload = dict[str, Any] | list[Any]


@dataclass(frozen=True, slots=True)
class FixtureMetadata:
    key: str
    path: PurePosixPath
    owner: str
    fixture_class: str
    expected_primary: str
    expected_secondary: tuple[str, ...]
    payload_fingerprint: str
    canonical_name: str | None = None
    contract_version: str | None = None
    notes: str | None = None


def _json(path: Path) -> FixturePayload:
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    return cast(FixturePayload, json.loads(text))


def load_manifest() -> tuple[FixtureMetadata, ...]:
    """Load and fully validate the canonical fixture catalog."""

    manifest = _json(MANIFEST)
    if not isinstance(manifest, dict):
        raise ValueError("Fixture manifest must be a JSON object.")
    raw_entries = cast(list[dict[str, Any]], manifest["entries"])
    entries = tuple(
        FixtureMetadata(
            key=item["key"],
            path=PurePosixPath(item["path"]),
            owner=item["owner"],
            fixture_class=item["fixture_class"],
            expected_primary=item["expected_primary"],
            expected_secondary=tuple(item.get("expected_secondary", ())),
            payload_fingerprint=item["payload_fingerprint"],
            canonical_name=item.get("canonical_name"),
            contract_version=item.get("contract_version"),
            notes=item.get("notes"),
        )
        for item in raw_entries
    )
    keys = tuple(item.key for item in entries)
    paths = tuple(item.path.as_posix() for item in entries)
    if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
        raise ValueError("Fixture keys must be unique and canonically ordered.")
    if len(paths) != len(set(paths)):
        raise ValueError("Fixture paths must be unique.")
    for item in entries:
        if _KEY_RE.fullmatch(item.key) is None:
            raise ValueError(f"Invalid fixture key: {item.key}")
        if item.path.is_absolute() or ".." in item.path.parts:
            raise ValueError(f"Unsafe fixture path: {item.path}")
        if item.fixture_class not in FIXTURE_CLASSES:
            raise ValueError(f"Unknown fixture class: {item.fixture_class}")
        payload = _json(FIXTURES / Path(*item.path.parts))
        if compute_fingerprint(payload) != item.payload_fingerprint:
            raise ValueError(f"Stale fixture fingerprint: {item.key}")
    expected_manifest_fingerprint = compute_fingerprint(raw_entries)
    if manifest["manifest_fingerprint"] != expected_manifest_fingerprint:
        raise ValueError("Fixture manifest fingerprint is stale.")
    disk_paths = {
        path.relative_to(FIXTURES).as_posix()
        for path in FIXTURES.rglob("*.json")
        if path != MANIFEST
    }
    if set(paths) != disk_paths:
        raise ValueError("Fixture manifest and JSON files do not match exactly.")
    return entries


def load_fixture(metadata: FixtureMetadata) -> FixturePayload:
    """Return detached JSON data for one catalog entry."""

    payload = _json(FIXTURES / Path(*metadata.path.parts))
    return deepcopy(payload)


def fixture_ids(metadata: FixtureMetadata) -> str:
    return metadata.key


__all__ = (
    "FIXTURES",
    "FIXTURE_CLASSES",
    "MANIFEST",
    "FixtureMetadata",
    "FixturePayload",
    "fixture_ids",
    "load_fixture",
    "load_manifest",
)
