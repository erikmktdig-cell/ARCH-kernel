"""Tests for dependency edge contracts."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import DependencyEdge

_FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "valid" / "minimal_project_state.json"


def test_dependency_edge_rejects_self_reference_and_requires_reason_when_needed() -> None:
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    edge = payload["dependency_graph"][0]

    with pytest.raises(ValidationError, match="cannot be identical"):
        DependencyEdge.model_validate_json(json.dumps({**edge, "target": edge["source"]}))
    with pytest.raises(ValidationError, match="reason is required"):
        DependencyEdge.model_validate_json(
            json.dumps({**edge, "dependency_type": "blocks", "reason": None})
        )
