"""Property tests for patch round-trips, purity, and deterministic dry runs."""

from datetime import timedelta

from hypothesis import given
from hypothesis import strategies as st

from arch_kernel.contracts import (
    ExecutionStatus,
    PatchOperationType,
    PatchPath,
    StatePatch,
)
from arch_kernel.kernel import apply_state_patch_dry_run
from tests.patch_helpers import PATCH_TIME, load_state, operation, patch

_SEGMENT = st.from_regex(r"[A-Za-z0-9][A-Za-z0-9_-]{0,15}", fullmatch=True).filter(
    lambda value: "__" not in value
)
_JSON_SCALARS = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text()
)
_JSON_VALUES = st.recursive(
    _JSON_SCALARS,
    lambda children: (
        st.lists(children, max_size=3) | st.dictionaries(st.text(), children, max_size=3)
    ),
    max_leaves=12,
)


@given(st.lists(_SEGMENT, min_size=1, max_size=5))
def test_canonical_patch_paths_round_trip(segments: list[str]) -> None:
    value = "/" + "/".join(segments)

    assert str(PatchPath.parse(value)) == value


@given(_JSON_VALUES)
def test_patch_values_round_trip_without_loss(value: object) -> None:
    state_patch = patch(operation(PatchOperationType.REPLACE, "/profile/project_type", value=value))

    restored = StatePatch.model_validate_json(state_patch.model_dump_json())

    assert restored.model_dump(mode="json") == state_patch.model_dump(mode="json")


@given(st.from_regex(r"[a-z][a-z0-9_-]{0,20}", fullmatch=True))
def test_dry_run_is_deterministic_and_never_mutates_original(project_type: str) -> None:
    state = load_state()
    before = state.canonical_json()
    state_patch = patch(
        operation(
            PatchOperationType.REPLACE,
            "/profile/project_type",
            value=project_type,
        ),
        state=state,
    )
    evaluated_at = PATCH_TIME + timedelta(minutes=2)

    first = apply_state_patch_dry_run(state, state_patch, evaluated_at=evaluated_at)
    second = apply_state_patch_dry_run(state, state_patch, evaluated_at=evaluated_at)

    assert first == second
    assert first.status is ExecutionStatus.COMPLETED
    assert state.canonical_json() == before


@given(st.from_regex(r"[a-z][a-z0-9_-]{0,20}", fullmatch=True))
def test_test_operations_do_not_report_changed_paths(value: str) -> None:
    state = load_state()
    state_patch = patch(
        operation(PatchOperationType.TEST, "/profile/project_type", value=value),
        state=state,
    )

    result = apply_state_patch_dry_run(state, state_patch)

    if value == state.profile.project_type:
        assert result.status is ExecutionStatus.COMPLETED
        assert result.changed_paths == ()
    else:
        assert result.status is ExecutionStatus.CONFLICT_DETECTED
        assert result.projected_state is None
