"""Transition definition strategies."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from arch_kernel.contracts import TransitionDefinition
from tests.transition_helpers import effect


def transition_definitions() -> SearchStrategy[TransitionDefinition]:
    return st.just(effect())


__all__ = ("transition_definitions",)
