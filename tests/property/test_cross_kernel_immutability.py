"""Cross-kernel purity and deep immutability properties."""

from __future__ import annotations

import pytest

from arch_kernel.contracts import PatchOperationType
from arch_kernel.kernel import (
    apply_state_patch_dry_run,
    audit_contract_registry,
    build_builtin_contract_registry,
    build_registry_manifest,
    evaluate_invariants,
    run_validation_pipeline,
)
from tests.invariant_helpers import canonical_registry, context
from tests.patch_helpers import load_state, operation, patch, replacement_profile
from tests.validation_helpers import state_request


def test_patch_invariant_validation_and_schema_operations_preserve_inputs() -> None:
    state = load_state()
    state_before = state.model_dump_json()
    state_patch = patch(
        operation(
            PatchOperationType.REPLACE,
            "/profile",
            value=replacement_profile(state),
        ),
        state=state,
    )
    patch_before = state_patch.model_dump_json()
    invariants = canonical_registry()
    definitions_before = invariants.definitions
    contracts = build_builtin_contract_registry()
    descriptors_before = contracts.descriptors

    patch_result = apply_state_patch_dry_run(state, state_patch)
    evaluate_invariants(context(state), invariants)
    run_validation_pipeline(state_request(state), invariant_registry=invariants)
    audit_contract_registry(contracts)

    assert state.model_dump_json() == state_before
    assert state_patch.model_dump_json() == patch_before
    assert invariants.definitions == definitions_before
    assert contracts.descriptors == descriptors_before
    assert patch_result.projected_state is not state


def test_frozen_nested_outputs_reject_mutation() -> None:
    contracts = build_builtin_contract_registry()
    manifest = build_registry_manifest(contracts)

    with pytest.raises(AttributeError):
        contracts.catalog_fingerprint = "changed"
    with pytest.raises(TypeError):
        manifest.build_metadata["changed"] = True  # type: ignore[index]
