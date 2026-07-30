"""Canonical ID and UTC strategies."""

from __future__ import annotations

from datetime import UTC, datetime

from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from arch_kernel.contracts.ids import (
    CANONICAL_ID_TYPES,
    CROCKFORD_BASE32_ALPHABET,
    CanonicalId,
)

_FIRST_ULID_CHARS = "01234567"


def canonical_ulids() -> SearchStrategy[str]:
    return st.builds(
        str.__add__,
        st.sampled_from(tuple(_FIRST_ULID_CHARS)),
        st.text(
            alphabet=CROCKFORD_BASE32_ALPHABET,
            min_size=25,
            max_size=25,
        ),
    )


@st.composite
def typed_ids(
    draw: st.DrawFn,
    id_types: tuple[type[CanonicalId], ...] = CANONICAL_ID_TYPES,
) -> CanonicalId:
    id_type = draw(st.sampled_from(id_types))
    ulid = draw(canonical_ulids())
    return id_type.from_str(f"{id_type.prefix}-{ulid}")


def utc_datetimes() -> SearchStrategy[datetime]:
    return st.datetimes(
        min_value=datetime(2000, 1, 1),
        max_value=datetime(2100, 1, 1),
        timezones=st.just(UTC),
        allow_imaginary=False,
    )


__all__ = ("canonical_ulids", "typed_ids", "utc_datetimes")
