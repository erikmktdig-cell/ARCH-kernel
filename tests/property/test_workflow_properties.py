"""Property evidence for deterministic generic workflow mechanics."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from arch_kernel.contracts import WorkflowStateKey
from arch_kernel.kernel import TransitionRegistry
from tests.workflow_helpers import workflow_definition, workflow_transition

STATE_TOKEN = st.from_regex(r"[a-z][a-z0-9_]{0,11}", fullmatch=True)


@given(st.sets(STATE_TOKEN, min_size=2, max_size=8))
def test_workflow_definition_fingerprint_is_independent_of_state_input_order(
    states: set[str],
) -> None:
    ordered = tuple(sorted(states))
    reversed_order = tuple(reversed(ordered))
    first = workflow_definition(states=ordered, initial_state=ordered[0])
    second = workflow_definition(states=reversed_order, initial_state=ordered[0])

    assert first.allowed_states == second.allowed_states
    assert first.definition_fingerprint() == second.definition_fingerprint()


@given(STATE_TOKEN, STATE_TOKEN)
def test_workflow_state_tokens_round_trip_exactly(first: str, second: str) -> None:
    assert str(WorkflowStateKey.parse(first)) == first
    assert str(WorkflowStateKey.parse(second)) == second


@given(st.permutations((0, 1, 2)))
def test_transition_registry_order_is_independent_of_insertion(permutation: list[int]) -> None:
    definition = workflow_definition(states=("draft", "approved", "released"))
    transitions = (
        workflow_transition(
            definition,
            key="workflow.first",
            transition_id="TRN-01HZX7M3FQ1T2Q9V8Y6K4C2B1A",
            priority=10,
        ),
        workflow_transition(
            definition,
            key="workflow.second",
            transition_id="TRN-01HZX7M3FQ1T2Q9V8Y6K4C2B1B",
            priority=20,
        ),
        workflow_transition(
            definition,
            source="approved",
            destination="released",
            key="workflow.third",
            transition_id="TRN-01HZX7M3FQ1T2Q9V8Y6K4C2B1C",
            priority=30,
        ),
    )
    registry = TransitionRegistry(tuple(transitions[index] for index in permutation), (definition,))

    assert registry.definitions == transitions
