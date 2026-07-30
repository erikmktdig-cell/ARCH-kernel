"""Property-oriented checks for deterministic WP-K06 behavior."""

from itertools import permutations

from hypothesis import given
from hypothesis import strategies as st

from arch_kernel.contracts import TransitionDefinition, TransitionDomain, TransitionId
from arch_kernel.kernel import TransitionRegistry, evaluate_transition
from tests.transition_helpers import (
    EVALUATED_AT,
    artifact_review_state,
    effect,
    registry,
    request,
)


def test_registry_order_never_changes_lookup_results() -> None:
    definitions = (
        effect(priority=30),
        effect(
            priority=10,
            key="artifact.accept",
            transition_id=TransitionId.from_str("TRN-01HZX7M3FQ1T2Q9V8Y6K4C2B1W"),
        ),
        effect(
            priority=20,
            key="artifact.confirm",
            transition_id=TransitionId.from_str("TRN-01HZX7M3FQ1T2Q9V8Y6K4C2B1X"),
        ),
    )
    expected = TransitionRegistry(definitions).definitions

    for ordering in permutations(definitions):
        assert TransitionRegistry(ordering).definitions == expected


@given(
    priority=st.integers(min_value=-10_000, max_value=10_000),
    description=st.one_of(st.none(), st.text(min_size=1).filter(lambda value: value.strip() != "")),
)
def test_definitions_survive_json_round_trip(priority: int, description: str | None) -> None:
    definition = effect(priority=priority).model_copy(update={"description": description})
    assert TransitionDefinition.model_validate_json(definition.model_dump_json()) == definition


@given(source=st.sampled_from(["draft", "proposed", "under_review", "rejected"]))
def test_source_state_validation_cannot_be_bypassed(source: str) -> None:
    state = artifact_review_state()
    definition = effect(source=source)
    result = evaluate_transition(
        state,
        request(state, definition),
        registry(definition),
        evaluated_at=EVALUATED_AT,
    )
    assert result.allowed is (source == "under_review")


def test_generated_patch_paths_remain_inside_domain_scope() -> None:
    state = artifact_review_state()
    definition = effect()
    result = evaluate_transition(state, request(state, definition), registry(definition))

    assert result.state_patch is not None
    scope = result.state_patch.scope[0]
    assert scope.segments[0] == "artifacts"
    assert all(operation.path.is_within(scope) for operation in result.state_patch.operations)
    assert definition.domain is TransitionDomain.ARTIFACT_STATUS


def test_evaluation_is_pure_and_fixed_inputs_are_identical() -> None:
    state = artifact_review_state()
    original = state.canonical_json()
    definition = effect()
    transition_request = request(state, definition)
    transition_registry = registry(definition)

    results = tuple(
        evaluate_transition(
            state,
            transition_request,
            transition_registry,
            evaluated_at=EVALUATED_AT,
        )
        for _ in range(3)
    )

    assert state.canonical_json() == original
    assert len({result.model_dump_json() for result in results}) == 1
