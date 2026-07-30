"""Unified validation request strategies."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from arch_kernel.contracts import ValidationPipelineRequest
from tests.patch_helpers import load_state
from tests.validation_helpers import state_request


def validation_requests() -> SearchStrategy[ValidationPipelineRequest]:
    return st.builds(lambda: state_request(load_state()).model_copy(deep=True))


__all__ = ("validation_requests",)
