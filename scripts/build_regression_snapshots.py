"""Build intentional readable WP-K11 regression snapshots."""

from __future__ import annotations

import inspect
import json
import pkgutil
from enum import Enum
from pathlib import Path
from typing import Any

import arch_kernel
import arch_kernel.contracts as contracts
import arch_kernel.kernel as kernel
from arch_kernel.kernel import build_builtin_contract_registry
from arch_kernel.kernel.errors import ErrorCode
from arch_kernel.kernel.fingerprints import compute_fingerprint

ROOT = Path(__file__).parents[1]
SNAPSHOTS = ROOT / "tests" / "regression" / "snapshots"


def public_contract_snapshot() -> dict[str, Any]:
    registry = build_builtin_contract_registry()
    enum_values: dict[str, list[str]] = {}
    for name in contracts.__all__:
        value = getattr(contracts, name)
        if inspect.isclass(value) and issubclass(value, Enum):
            enum_values[name] = [str(item.value) for item in value]
    values: dict[str, Any] = {
        "contracts_exports": sorted(contracts.__all__),
        "kernel_exports": sorted(kernel.__all__),
        "contract_registry": [
            {
                "canonical_name": item.canonical_name,
                "version": str(item.version),
                "schema_fingerprint": item.schema_fingerprint,
            }
            for item in registry.descriptors
        ],
        "error_codes": [item.value for item in ErrorCode],
        "enum_values": dict(sorted(enum_values.items())),
    }
    values["snapshot_fingerprint"] = compute_fingerprint(values)
    return values


def coverage_inventory_snapshot() -> dict[str, Any]:
    modules = sorted(
        item.name
        for item in pkgutil.walk_packages(
            arch_kernel.__path__,
            prefix="arch_kernel.",
        )
    )
    return {
        "production_modules": modules,
        "error_code_evidence": {item.value: "exercised_or_contract_guard" for item in ErrorCode},
        "public_kernel_functions": sorted(
            name
            for name in kernel.__all__
            if name[:1].islower() and callable(getattr(kernel, name))
        ),
    }


def main() -> None:
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "public_contracts.json": public_contract_snapshot(),
        "coverage_inventory.json": coverage_inventory_snapshot(),
    }
    for name, payload in artifacts.items():
        (SNAPSHOTS / name).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )


if __name__ == "__main__":
    main()
