"""Event fixture strategies."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import cast

from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from arch_kernel.contracts import EventEnvelope

_EVENT = Path(__file__).parents[2] / "fixtures" / "valid" / "event_envelope.json"


def _payload() -> dict[str, object]:
    return cast(dict[str, object], json.loads(_EVENT.read_text(encoding="utf-8")))


def valid_events() -> SearchStrategy[EventEnvelope]:
    return st.builds(lambda: EventEnvelope.model_validate_json(json.dumps(deepcopy(_payload()))))


def invalid_event_payloads() -> SearchStrategy[dict[str, object]]:
    return st.sampled_from(
        [
            {**_payload(), "event_type": "INVALID"},
            {**_payload(), "recorded_at": "2020-01-01T00:00:00"},
        ]
    ).map(deepcopy)


__all__ = ("invalid_event_payloads", "valid_events")
