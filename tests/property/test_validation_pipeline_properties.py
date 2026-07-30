"""Property coverage for deterministic K08 pipeline behavior."""

from __future__ import annotations

from datetime import timedelta

from hypothesis import given
from hypothesis import strategies as st

from arch_kernel.contracts import ValidationPipelineResult
from arch_kernel.kernel import run_validation_pipeline
from tests.validation_helpers import EVALUATED_AT, state_request


@given(st.integers(min_value=0, max_value=365))
def test_semantically_identical_state_validation_is_time_independent(days: int) -> None:
    request = state_request().model_copy(
        update={"evaluated_at": EVALUATED_AT + timedelta(days=days)}
    )
    baseline = run_validation_pipeline(state_request())
    candidate = run_validation_pipeline(request)
    assert candidate.input_fingerprint == baseline.input_fingerprint
    assert candidate.result_fingerprint == baseline.result_fingerprint


@given(st.integers(min_value=1, max_value=5))
def test_json_round_trip_is_idempotent(repetitions: int) -> None:
    result = run_validation_pipeline(state_request())
    for _ in range(repetitions):
        result = ValidationPipelineResult.model_validate_json(result.model_dump_json())
    assert result == run_validation_pipeline(state_request())
