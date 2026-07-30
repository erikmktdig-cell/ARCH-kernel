"""Deterministic builders for WP-K08 validation pipeline tests."""

from __future__ import annotations

from datetime import UTC, datetime

from arch_kernel.contracts import (
    InvariantEvaluationTarget,
    PatchOperationType,
    ProjectState,
    ValidationIntent,
    ValidationPipelinePolicy,
    ValidationPipelineRequest,
)
from tests.invariant_helpers import canonical_registry as invariant_registry
from tests.patch_helpers import load_state as load_state
from tests.patch_helpers import (
    operation,
    patch,
    replacement_profile,
)
from tests.transition_helpers import (
    artifact_review_state,
    effect,
)
from tests.transition_helpers import (
    registry as transition_registry_for,
)
from tests.transition_helpers import (
    request as transition_request_for,
)

EVALUATED_AT = datetime(2026, 7, 26, 15, 0, tzinfo=UTC)


def state_request(
    state: ProjectState | None = None,
    *,
    intent: ValidationIntent = ValidationIntent.VALIDATE_STATE,
    policy: ValidationPipelinePolicy | None = None,
    **changes: object,
) -> ValidationPipelineRequest:
    return ValidationPipelineRequest.model_validate(
        {
            "intent": intent,
            "evaluated_at": EVALUATED_AT,
            "state": state or load_state(),
            "policy": policy or ValidationPipelinePolicy(),
            **changes,
        }
    )


def patch_request(
    state: ProjectState | None = None,
    *,
    policy: ValidationPipelinePolicy | None = None,
    **patch_changes: object,
) -> ValidationPipelineRequest:
    current = state or load_state()
    state_patch = patch(
        operation(
            PatchOperationType.REPLACE,
            "/profile",
            value=replacement_profile(current),
        ),
        state=current,
    )
    if patch_changes:
        state_patch = state_patch.model_copy(update=patch_changes)
    return state_request(
        current,
        intent=ValidationIntent.VALIDATE_PATCH,
        patch=state_patch,
        policy=policy,
    )


def transition_request() -> tuple[ValidationPipelineRequest, object]:
    state = artifact_review_state()
    definition = effect()
    request = state_request(
        state,
        intent=ValidationIntent.VALIDATE_TRANSITION,
        transition_request=transition_request_for(state, definition),
    )
    return request, transition_registry_for(definition)


def projected_policy() -> ValidationPipelinePolicy:
    return ValidationPipelinePolicy(invariant_target=InvariantEvaluationTarget.PROJECTED)


__all__ = (
    "EVALUATED_AT",
    "invariant_registry",
    "load_state",
    "patch_request",
    "projected_policy",
    "state_request",
    "transition_request",
)
