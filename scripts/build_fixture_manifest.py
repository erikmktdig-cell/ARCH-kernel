"""Build the deterministic WP-K11 fixture manifest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from arch_kernel.kernel.fingerprints import compute_fingerprint

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "fixtures"
MANIFEST = FIXTURES / "manifest.json"
OWNERS = {
    "base_models": "WP-K02",
    "contract_registry": "WP-K09",
    "events": "WP-K04",
    "invariants": "WP-K07",
    "migrations": "WP-K10",
    "primitives": "WP-K01",
    "project_state": "WP-K03",
    "regression": "WP-K11",
    "state_patch": "WP-K05",
    "transitions": "WP-K06",
    "validation_pipeline": "WP-K08",
}


def _metadata(path: Path) -> dict[str, Any]:
    relative = path.relative_to(FIXTURES).as_posix()
    parts = path.relative_to(FIXTURES).parts
    validity = parts[0]
    package = (
        parts[1] if len(parts) > 2 else ("events" if "event" in path.stem else "project_state")
    )
    if package == "regression":
        fixture_class = "regression"
        expected = "FINGERPRINT_STABLE"
    elif path.stem == "non_blocking_finding":
        fixture_class = "non_blocking_finding"
        expected = "ACCEPTED_WITH_FINDINGS"
    elif package == "migrations":
        fixture_class = "migration_success" if validity == "valid" else "migration_failure"
        expected = "SUCCEEDED" if validity == "valid" else "FAILED"
    elif validity == "valid":
        fixture_class = "valid"
        expected = "VALID"
    elif package == "project_state":
        fixture_class = "invalid_aggregate"
        expected = "AGGREGATE_VALIDATION_FAILED"
    elif package in {"events", "contract_registry"}:
        fixture_class = "invalid_contract"
        expected = "CONTRACT_VALIDATION_FAILED"
    else:
        fixture_class = "rejected_policy"
        expected = "REJECTED"
    payload = json.loads(path.read_text(encoding="utf-8"))
    key = relative.removesuffix(".json").replace("/", ".").replace("-", "_")
    return {
        "key": key,
        "path": relative,
        "owner": OWNERS.get(package, "WP-K03"),
        "fixture_class": fixture_class,
        "expected_primary": expected,
        "payload_fingerprint": compute_fingerprint(payload),
    }


def build_manifest() -> dict[str, Any]:
    """Build the complete manifest without filesystem side effects."""

    entries = sorted(
        (_metadata(path) for path in FIXTURES.rglob("*.json") if path != MANIFEST),
        key=lambda item: item["key"],
    )
    return {
        "manifest_version": "1.0.0",
        "entries": entries,
        "manifest_fingerprint": compute_fingerprint(entries),
    }


def main() -> None:
    manifest = build_manifest()
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
