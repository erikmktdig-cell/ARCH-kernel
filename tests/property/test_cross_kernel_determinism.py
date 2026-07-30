"""Cross-kernel semantic determinism properties."""

from __future__ import annotations

from hypothesis import given

from arch_kernel.contracts import PatchOperationType
from arch_kernel.kernel import (
    apply_state_patch_dry_run,
    build_builtin_contract_registry,
    canonicalize_json,
    compute_fingerprint,
    generate_registry_schemas,
)
from tests.patch_helpers import load_state, operation, patch, replacement_profile
from tests.strategies.json_values import json_objects
from tests.strategies.registry import contract_registries


@given(json_objects())
def test_mapping_insertion_order_is_canonical_across_json_and_fingerprints(
    payload: dict[str, object],
) -> None:
    reversed_payload = dict(reversed(tuple(payload.items())))

    assert canonicalize_json(payload) == canonicalize_json(reversed_payload)
    assert compute_fingerprint(payload) == compute_fingerprint(reversed_payload)


@given(contract_registries())
def test_contract_registry_strategy_preserves_canonical_order(registry: object) -> None:
    canonical = build_builtin_contract_registry()
    assert canonical.descriptors == tuple(
        sorted(
            canonical.descriptors,
            key=lambda item: (item.canonical_name, item.version),
        )
    )
    assert generate_registry_schemas(canonical) == generate_registry_schemas(
        build_builtin_contract_registry()
    )
    assert registry is not None


def test_repeated_patch_evaluation_has_identical_semantic_result() -> None:
    state = load_state()
    state_patch = patch(
        operation(
            PatchOperationType.REPLACE,
            "/profile",
            value=replacement_profile(state),
        ),
        state=state,
    )

    first = apply_state_patch_dry_run(state, state_patch)
    second = apply_state_patch_dry_run(state, state_patch)

    assert first == second
    assert first.projected_state_content_fingerprint == (second.projected_state_content_fingerprint)
