from hypothesis import given, settings
from hypothesis import strategies as st

from arch_kernel.contracts import SemanticVersion

numeric_identifier = st.integers(min_value=0, max_value=999).map(str)
non_numeric_identifier = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="-",
    ),
    min_size=1,
    max_size=8,
).filter(lambda value: all(ord(char) < 128 for char in value) and not value.isdigit())
identifier = numeric_identifier | non_numeric_identifier


@given(
    major=st.integers(min_value=0, max_value=999),
    minor=st.integers(min_value=0, max_value=999),
    patch=st.integers(min_value=0, max_value=999),
)
@settings(max_examples=40)
def test_core_semantic_versions_round_trip(major: int, minor: int, patch: int) -> None:
    value = f"{major}.{minor}.{patch}"

    assert str(SemanticVersion.parse(value)) == value


@given(
    major=st.integers(min_value=0, max_value=999),
    minor=st.integers(min_value=0, max_value=999),
    patch=st.integers(min_value=0, max_value=999),
    prerelease=st.lists(identifier, min_size=1, max_size=3).map(tuple),
)
@settings(max_examples=40)
def test_prerelease_semantic_versions_round_trip(
    major: int,
    minor: int,
    patch: int,
    prerelease: tuple[str, ...],
) -> None:
    version = SemanticVersion(major, minor, patch, prerelease=prerelease)

    assert SemanticVersion.parse(str(version)) == version
