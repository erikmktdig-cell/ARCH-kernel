from hypothesis import given, settings
from hypothesis import strategies as st

from arch_kernel.contracts import CANONICAL_ID_TYPES, ArtifactId
from arch_kernel.contracts.ids import CROCKFORD_BASE32_ALPHABET

id_type_indices = st.integers(min_value=0, max_value=len(CANONICAL_ID_TYPES) - 1)
valid_ulid_texts = st.tuples(
    st.sampled_from("01234567"),
    st.lists(
        st.sampled_from(CROCKFORD_BASE32_ALPHABET),
        min_size=25,
        max_size=25,
    ),
).map(lambda parts: parts[0] + "".join(parts[1]))


@given(id_type_index=id_type_indices)
@settings(max_examples=25)
def test_generated_ids_round_trip_by_type(id_type_index: int) -> None:
    id_type = CANONICAL_ID_TYPES[id_type_index]
    generated = id_type.generate()

    assert id_type.from_str(str(generated)) == generated


@given(id_type_index=id_type_indices)
@settings(max_examples=25)
def test_generated_ids_are_not_empty_and_use_canonical_separator(id_type_index: int) -> None:
    id_type = CANONICAL_ID_TYPES[id_type_index]
    generated = id_type.generate()
    prefix, ulid = str(generated).split("-", 1)

    assert prefix == id_type.prefix
    assert len(ulid) == 26


@given(ulid_text=valid_ulid_texts)
@settings(max_examples=25)
def test_artifact_id_round_trip_for_valid_ulid_text(ulid_text: str) -> None:
    value = f"ART-{ulid_text}"
    artifact_id = ArtifactId.from_str(value)

    assert str(artifact_id) == value
