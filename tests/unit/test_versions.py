import pytest
from pydantic import BaseModel, ValidationError

from arch_kernel.contracts import SemanticVersion
from arch_kernel.kernel import VersionValidationError


class VersionContainer(BaseModel):
    version: SemanticVersion


@pytest.mark.parametrize(
    "value",
    [
        "1.0.0",
        "1.2.3-alpha",
        "1.2.3-alpha.1",
        "1.2.3+build.5",
        "1.2.3-rc.1+sha.abc123",
    ],
)
def test_valid_semantic_versions_round_trip(value: str) -> None:
    version = SemanticVersion.parse(value)

    assert str(version) == value
    assert SemanticVersion.parse(str(version)).is_identical_to(version)


@pytest.mark.parametrize(
    "value",
    [
        "1",
        "1.2",
        "01.2.3",
        "1.02.3",
        "1.2.03",
        "1.0.0-01",
        "1.0.0-alpha..1",
        "1.0.0-alpha_1",
        "1.0.0+",
    ],
)
def test_invalid_semantic_versions_are_rejected(value: str) -> None:
    with pytest.raises(VersionValidationError):
        SemanticVersion.parse(value)


def test_semantic_version_precedence_examples() -> None:
    ordered = [
        "1.0.0-alpha",
        "1.0.0-alpha.1",
        "1.0.0-alpha.beta",
        "1.0.0-beta",
        "1.0.0-beta.2",
        "1.0.0-beta.11",
        "1.0.0-rc.1",
        "1.0.0",
    ]
    parsed = [SemanticVersion.parse(value) for value in ordered]

    assert parsed == sorted(parsed)
    assert SemanticVersion.parse("1.0.0-alpha") < SemanticVersion.parse("1.0.0")
    assert SemanticVersion.parse("1.0.0") < SemanticVersion.parse("2.0.0")
    assert not (SemanticVersion.parse("1.0.0-alpha") < SemanticVersion.parse("1.0.0-alpha"))


def test_build_metadata_is_ignored_for_equality_and_hashing() -> None:
    first = SemanticVersion.parse("1.0.0+build.1")
    second = SemanticVersion.parse("1.0.0+build.2")

    assert first == second
    assert hash(first) == hash(second)
    assert not first.is_identical_to(second)


def test_semantic_version_constructor_validates_values() -> None:
    with pytest.raises(VersionValidationError):
        SemanticVersion(-1, 0, 0)

    with pytest.raises(VersionValidationError):
        SemanticVersion(True, 0, 0)

    with pytest.raises(VersionValidationError):
        SemanticVersion(1, 0, 0, prerelease=["alpha"])  # type: ignore[arg-type]

    with pytest.raises(VersionValidationError):
        SemanticVersion(1, 0, 0, prerelease=("",))

    with pytest.raises(VersionValidationError):
        SemanticVersion(1, 0, 0, prerelease=("01",))

    with pytest.raises(VersionValidationError):
        SemanticVersion(1, 0, 0, build=("bad_value",))


def test_semantic_version_rejects_non_string_parse_input() -> None:
    with pytest.raises(VersionValidationError):
        SemanticVersion.parse(123)  # type: ignore[arg-type]


def test_semantic_version_repr_and_non_version_comparisons() -> None:
    version = SemanticVersion.parse("1.2.3")

    assert repr(version) == "SemanticVersion.parse('1.2.3')"
    assert version != "1.2.3"
    assert version.__lt__("1.2.3") is NotImplemented


def test_pydantic_parses_and_serializes_semantic_version() -> None:
    container = VersionContainer.model_validate({"version": "1.2.3-rc.1+sha.abc123"})

    assert container.version == SemanticVersion.parse("1.2.3-rc.1")
    assert container.version.is_identical_to(SemanticVersion.parse("1.2.3-rc.1+sha.abc123"))
    assert container.model_dump(mode="json") == {"version": "1.2.3-rc.1+sha.abc123"}


def test_pydantic_rejects_invalid_semantic_version() -> None:
    with pytest.raises(ValidationError):
        VersionContainer.model_validate({"version": "1.02.3"})


def test_pydantic_json_schema_contains_semver_pattern() -> None:
    schema = VersionContainer.model_json_schema()

    assert schema["properties"]["version"]["type"] == "string"
    assert schema["properties"]["version"]["pattern"] == SemanticVersion.pattern
