"""Invariant definition strategies."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from arch_kernel.contracts import InvariantDefinition
from tests.invariant_helpers import canonical_definitions


def invariant_definitions() -> SearchStrategy[InvariantDefinition]:
    return st.sampled_from(canonical_definitions())


__all__ = ("invariant_definitions",)
