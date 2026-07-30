"""Tests for artifact records."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import ArtifactRecord

_FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "valid" / "minimal_project_state.json"


def test_artifact_rejects_invalid_fingerprint_and_self_supersession() -> None:
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    artifact = next(iter(payload["artifact_registry"].values()))

    with pytest.raises(ValidationError, match="content_fingerprint"):
        ArtifactRecord.model_validate_json(
            json.dumps({**artifact, "content_fingerprint": "not-a-fingerprint"})
        )
    with pytest.raises(ValidationError, match="cannot supersede itself"):
        ArtifactRecord.model_validate_json(
            json.dumps({**artifact, "supersedes": artifact["artifact_id"]})
        )
