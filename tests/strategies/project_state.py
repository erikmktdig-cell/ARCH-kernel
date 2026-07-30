"""ProjectState strategies derived from approved aggregate fixtures."""

from __future__ import annotations

from copy import deepcopy

from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from arch_kernel.contracts import ProjectState
from tests.patch_helpers import load_state


def valid_project_states() -> SearchStrategy[ProjectState]:
    return st.builds(lambda: load_state().model_copy(deep=True))


def valid_project_state_payloads() -> SearchStrategy[dict[str, object]]:
    return valid_project_states().map(lambda state: deepcopy(state.model_dump(mode="json")))


def invalid_project_state_payloads() -> SearchStrategy[dict[str, object]]:
    def invalidate(payload: dict[str, object]) -> dict[str, object]:
        changed = deepcopy(payload)
        changed["project_id"] = "PRJ-invalid"
        return changed

    return valid_project_state_payloads().map(invalidate)


__all__ = (
    "invalid_project_state_payloads",
    "valid_project_state_payloads",
    "valid_project_states",
)
