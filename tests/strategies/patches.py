"""State patch strategies from canonical fixtures."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import cast

from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from arch_kernel.contracts import StatePatch

_ROOT = Path(__file__).parents[2] / "fixtures" / "valid" / "state_patch"
_FILES = (
    _ROOT / "add_risk_record.json",
    _ROOT / "replace_project_profile.json",
    _ROOT / "test_then_replace.json",
)


def _load(path: Path) -> StatePatch:
    payload = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
    return StatePatch.model_validate(deepcopy(payload))


def valid_state_patches() -> SearchStrategy[StatePatch]:
    return st.sampled_from(_FILES).map(_load)


__all__ = ("valid_state_patches",)
