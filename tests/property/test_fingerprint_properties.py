"""Property tests for canonical JSON and fingerprint determinism."""

from hypothesis import given
from hypothesis import strategies as st

from arch_kernel.kernel import canonicalize_json, compute_fingerprint

_JSON_SCALARS = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text()
)
_JSON_VALUES = st.recursive(
    _JSON_SCALARS,
    lambda children: (
        st.lists(children, max_size=5) | st.dictionaries(st.text(), children, max_size=5)
    ),
    max_leaves=20,
)


@given(_JSON_VALUES)
def test_canonicalization_and_fingerprints_are_deterministic(value: object) -> None:
    assert canonicalize_json(value) == canonicalize_json(value)
    assert compute_fingerprint(value) == compute_fingerprint(value)


@given(st.dictionaries(st.text(), _JSON_VALUES, max_size=8))
def test_mapping_order_does_not_change_the_fingerprint(value: dict[str, object]) -> None:
    reversed_order = dict(reversed(tuple(value.items())))

    assert compute_fingerprint(value) == compute_fingerprint(reversed_order)


@given(st.integers(), st.integers().filter(lambda candidate: candidate != 0))
def test_changing_a_json_value_changes_its_fingerprint(value: int, delta: int) -> None:
    assert compute_fingerprint({"value": value}) != compute_fingerprint({"value": value + delta})
