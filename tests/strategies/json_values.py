"""Strict bounded JSON-safe strategies."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
_KEY_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-."


def json_scalars() -> SearchStrategy[JsonScalar]:
    return st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-(2**31), max_value=2**31 - 1),
        st.floats(
            min_value=-1e12,
            max_value=1e12,
            allow_nan=False,
            allow_infinity=False,
            width=64,
        ),
        st.text(max_size=40),
    )


def json_values(
    *,
    max_leaves: int = 20,
) -> SearchStrategy[JsonValue]:
    return st.recursive(
        json_scalars(),
        lambda children: st.one_of(
            st.lists(children, max_size=5),
            st.dictionaries(
                st.text(
                    alphabet=_KEY_ALPHABET,
                    min_size=1,
                    max_size=12,
                ),
                children,
                max_size=5,
            ),
        ),
        max_leaves=max_leaves,
    )


def json_objects() -> SearchStrategy[dict[str, JsonValue]]:
    return st.dictionaries(
        st.text(
            alphabet=_KEY_ALPHABET,
            min_size=1,
            max_size=12,
        ),
        json_values(max_leaves=12),
        max_size=6,
    )


__all__ = ("JsonScalar", "JsonValue", "json_objects", "json_scalars", "json_values")
