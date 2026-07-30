"""Shared deterministic builders for WP-K05 tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from arch_kernel.contracts import (
    ActorType,
    EventActor,
    PatchId,
    PatchOperation,
    PatchOperationType,
    PatchPath,
    ProjectState,
    SemanticVersion,
    StatePatch,
)

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures"
PATCH_TIME = datetime(2026, 7, 23, 13, 0, tzinfo=UTC)
VERSION = SemanticVersion.parse("1.0.0")


def load_state() -> ProjectState:
    payload = (FIXTURE_ROOT / "valid" / "minimal_project_state.json").read_text(encoding="utf-8")
    return ProjectState.model_validate_json(payload)


def actor() -> EventActor:
    return EventActor(
        contract_name="event_actor",
        contract_version=VERSION,
        schema_uri="urn:arch:contracts:event_actor:1.0.0",
        created_at=PATCH_TIME,
        actor_type=ActorType.HUMAN,
        actor_id="platform-engineer",
        display_name="Platform Engineer",
    )


def operation(
    op: PatchOperationType,
    path: str,
    *,
    value: object = ...,
    expected_record_version: int | None = None,
    expected_content_fingerprint: str | None = None,
) -> PatchOperation:
    fields: dict[str, object] = {
        "op": op,
        "path": PatchPath.parse(path),
        "expected_record_version": expected_record_version,
        "expected_content_fingerprint": expected_content_fingerprint,
    }
    if value is not ...:
        fields["value"] = value
    return PatchOperation.model_validate(fields)


def patch(
    *operations: PatchOperation,
    state: ProjectState | None = None,
    scope: tuple[str, ...] = ("/profile",),
    **changes: object,
) -> StatePatch:
    current = state or load_state()
    values = {
        "contract_name": "state_patch",
        "contract_version": VERSION,
        "schema_uri": "urn:arch:contracts:state_patch:1.0.0",
        "created_at": PATCH_TIME,
        "patch_id": PatchId.from_str("PATCH-01HZX7M3FQ1T2Q9V8Y6K4C2B1K"),
        "project_id": current.metadata.project_id,
        "base_state_record_version": current.record_version,
        "base_state_content_fingerprint": current.contract_content_fingerprint(),
        "operations": operations,
        "created_by": actor(),
        "reason": "Validate a deterministic state change.",
        "scope": tuple(PatchPath.parse(path) for path in scope),
        **changes,
    }
    return StatePatch.model_validate(values)


def replacement_profile(state: ProjectState | None = None) -> dict[str, object]:
    current = state or load_state()
    profile = current.profile.model_dump(mode="json")
    profile["project_type"] = "service"
    return profile


def new_risk_payload() -> dict[str, object]:
    return {
        "contract_name": "risk_record",
        "contract_version": "1.0.0",
        "schema_uri": "urn:arch:contracts:risk_record:1.0.0",
        "created_at": "2026-07-23T13:00:00Z",
        "updated_at": "2026-07-23T13:00:00Z",
        "record_version": 1,
        "state_version_created": 2,
        "state_version_updated": 2,
        "risk_id": "RISK-01HZX7M3FQ1T2Q9V8Y6K4C2B1J",
        "title": "Patch drift",
        "description": "Patch preconditions may become stale.",
        "probability": 2,
        "impact": 3,
        "status": "open",
        "owner": "platform-team",
        "mitigation": "Reload state before retrying.",
        "related_artifact_ids": [],
        "related_requirement_ids": [],
    }
