"""Catalog and published-schema stability regression checks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from arch_kernel.kernel import (
    build_builtin_contract_registry,
    build_registry_manifest,
)

ROOT = Path(__file__).parents[2]


def test_published_manifest_matches_exact_in_memory_catalog() -> None:
    published = cast(
        dict[str, Any],
        json.loads((ROOT / "schemas" / "manifest.json").read_text(encoding="utf-8")),
    )
    generated = build_registry_manifest(build_builtin_contract_registry()).model_dump(mode="json")

    assert published == generated


def test_catalog_contains_no_machine_specific_paths() -> None:
    text = (ROOT / "schemas" / "manifest.json").read_text(encoding="utf-8")

    assert "C:\\" not in text
    assert "/Users/" not in text
    assert "/home/" not in text


def test_public_snapshot_fingerprint_is_pythonhashseed_independent() -> None:
    command = (
        "from scripts.build_regression_snapshots import public_contract_snapshot;"
        "print(public_contract_snapshot()['snapshot_fingerprint'])"
    )
    outputs: list[str] = []
    for seed in ("1", "8675309"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", command],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        outputs.append(completed.stdout.strip())

    assert outputs[0] == outputs[1]
