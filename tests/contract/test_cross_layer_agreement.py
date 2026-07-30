"""Explicit agreement checks across approved K01-K10 layers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from arch_kernel.contracts import (
    InvariantKind,
    MigrationOperationType,
    MigrationPolicy,
    PatchOperationType,
    ProjectState,
    ValidationIntent,
)
from arch_kernel.kernel import (
    apply_state_patch_dry_run,
    build_builtin_contract_registry,
    evaluate_invariants,
    evaluate_transition,
    generate_contract_schema,
    run_migration_dry_run,
    run_validation_pipeline,
)
from arch_kernel.kernel.event_validation import thaw_json
from arch_kernel.kernel.invariant_registry import InvariantRegistry
from arch_kernel.kernel.migration_registry import MigrationRegistry
from tests.invariant_helpers import context, load_event
from tests.invariant_helpers import definition as invariant_definition
from tests.migration_helpers import (
    PayloadV1,
    PayloadV2,
    contract_registry,
)
from tests.migration_helpers import (
    definition as migration_definition,
)
from tests.migration_helpers import (
    operation as migration_operation,
)
from tests.migration_helpers import (
    request as migration_request,
)
from tests.patch_helpers import load_state, operation, patch, replacement_profile
from tests.transition_helpers import artifact_review_state, effect, registry, request
from tests.validation_helpers import state_request

ROOT = Path(__file__).parents[2]


def _json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def test_model_dump_validates_against_exact_published_k09_schema() -> None:
    contracts = build_builtin_contract_registry()
    registration = contracts.latest_active("arch.project.project_state")
    assert registration is not None
    schema = _json(ROOT / "schemas" / registration.descriptor.schema_filename)

    Draft202012Validator(schema).validate(load_state().model_dump(mode="json"))


def test_k05_projection_reconstructs_with_equal_content_fingerprint() -> None:
    state = load_state()
    result = apply_state_patch_dry_run(
        state,
        patch(
            operation(
                PatchOperationType.REPLACE,
                "/profile",
                value=replacement_profile(state),
            ),
            state=state,
        ),
    )
    assert result.projected_state is not None

    rebuilt = ProjectState.model_validate_json(result.projected_state.model_dump_json())
    assert rebuilt.contract_content_fingerprint() == (result.projected_state_content_fingerprint)


def test_k06_projection_equals_direct_k05_dry_run() -> None:
    state = artifact_review_state()
    transition = effect()
    evaluated = evaluate_transition(
        state,
        request(state, transition),
        registry(transition),
    )
    assert evaluated.state_patch is not None

    assert evaluated.dry_run_result == apply_state_patch_dry_run(state, evaluated.state_patch)


def test_k07_blocking_identity_is_preserved_by_k08() -> None:
    event = load_event()
    invariant = invariant_definition(InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY)
    invariants = InvariantRegistry((invariant,))
    invariant_result = evaluate_invariants(
        context(history=(event, event)),
        invariants,
    )
    validation_result = run_validation_pipeline(
        state_request(
            load_state(),
            intent=ValidationIntent.VALIDATE_HISTORY,
            event_history=(event, event),
        ),
        invariant_registry=invariants,
    )

    assert not invariant_result.success
    assert not validation_result.success
    assert validation_result.invariant_stage.findings[0].source_id == str(invariant.invariant_id)
    assert validation_result.invariant_stage.findings[0].source_key == (
        invariant_result.violations[0].key
    )


def test_k08_input_fingerprint_includes_invariant_registry_identity() -> None:
    first = InvariantRegistry((invariant_definition(InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY),))
    second = InvariantRegistry(
        (
            invariant_definition(
                InvariantKind.IMMUTABLE_HISTORY_CONSISTENCY,
                blocking=False,
            ),
        )
    )
    validation_request = state_request(load_state())

    left = run_validation_pipeline(
        validation_request,
        invariant_registry=first,
    )
    right = run_validation_pipeline(
        validation_request,
        invariant_registry=second,
    )

    assert left.input_fingerprint != right.input_fingerprint


def test_k09_manifest_resolves_exact_models_and_schema_fingerprints() -> None:
    contracts = build_builtin_contract_registry()
    for descriptor in contracts.descriptors:
        registration = contracts.get(
            descriptor.canonical_name,
            descriptor.version,
        )
        assert registration is not None
        assert registration.model.__module__ == descriptor.python_module
        assert (
            generate_contract_schema(registration).schema_fingerprint
            == descriptor.schema_fingerprint
        )


def test_k10_target_payload_validates_exact_target_model_and_schema() -> None:
    contracts = contract_registry((PayloadV1, "1.0.0"), (PayloadV2, "1.1.0"))
    migrations = MigrationRegistry((migration_definition(),), contracts)
    result = run_migration_dry_run(
        migration_request({"name": "alpha"}),
        migrations,
        contracts,
    )
    target = contracts.latest_active("arch.test.migration_payload")
    assert result.success
    assert target is not None
    payload = thaw_json(result.final_payload)
    assert isinstance(payload, dict)

    target.model.model_validate(payload)
    schema = generate_contract_schema(target)
    normalized_schema = thaw_json(schema.normalized_schema)
    assert isinstance(normalized_schema, dict)
    Draft202012Validator(normalized_schema).validate(payload)


def test_reversible_k10_fixture_round_trip_is_semantic_identity() -> None:
    contracts = contract_registry((PayloadV1, "1.0.0"), (PayloadV2, "1.1.0"))
    upgrade = migration_definition(
        index=0,
        reversible=True,
        reverse_index=1,
    )
    downgrade = migration_definition(
        index=1,
        source="1.1.0",
        target="1.0.0",
        operations=(migration_operation(MigrationOperationType.REMOVE, "/note"),),
        reversible=True,
        reverse_index=0,
    )
    migrations = MigrationRegistry((upgrade, downgrade), contracts)
    source = {"name": "alpha"}
    forward = run_migration_dry_run(
        migration_request(source),
        migrations,
        contracts,
    )
    forward_payload = thaw_json(forward.final_payload)
    assert isinstance(forward_payload, dict)
    reverse = run_migration_dry_run(
        migration_request(
            forward_payload,
            source="1.1.0",
            target="1.0.0",
            policy=MigrationPolicy(allow_downgrade=True),
        ),
        migrations,
        contracts,
    )

    assert thaw_json(reverse.final_payload) == source
