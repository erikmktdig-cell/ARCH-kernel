import re

import pytest
from pydantic import BaseModel, ValidationError

from arch_kernel.contracts import (
    CANONICAL_ID_TYPES,
    AnyCanonicalId,
    ArtifactId,
    PhaseId,
    RequirementId,
)
from arch_kernel.kernel import IdentifierValidationError


class ArtifactContainer(BaseModel):
    artifact_id: ArtifactId


class AnyIdContainer(BaseModel):
    identifier: AnyCanonicalId


class PhaseContainer(BaseModel):
    phase_id: PhaseId


def test_generate_each_canonical_id_type() -> None:
    for id_type in CANONICAL_ID_TYPES:
        generated = id_type.generate()

        assert isinstance(generated, id_type)
        assert str(generated).startswith(f"{id_type.prefix}-")
        assert re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{26}", generated.ulid) is not None


def test_generate_rejects_timestamp_outside_ulid_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def overflowing_time_ns() -> int:
        return (1 << 48) * 1_000_000

    monkeypatch.setattr("arch_kernel.contracts.ids.time.time_ns", overflowing_time_ns)

    with pytest.raises(OverflowError, match="48-bit ULID timestamp"):
        ArtifactId.generate()


def test_round_trip_string_equality_and_hashing() -> None:
    artifact_id = ArtifactId.generate()
    same_artifact_id = ArtifactId.from_str(str(artifact_id))

    assert same_artifact_id == artifact_id
    assert hash(same_artifact_id) == hash(artifact_id)
    assert str(same_artifact_id) == str(artifact_id)
    assert repr(artifact_id) == f"ArtifactId({str(artifact_id)!r})"


def test_wrong_prefix_is_rejected() -> None:
    artifact_id = ArtifactId.generate()

    with pytest.raises(IdentifierValidationError):
        RequirementId.from_str(str(artifact_id))


@pytest.mark.parametrize(
    "value",
    [
        "",
        "ART",
        "ART-",
        "ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1I",
        "ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1AA",
        "ART-ZZZZZZZZZZZZZZZZZZZZZZZZZZ",
    ],
)
def test_invalid_identifier_strings_are_rejected(value: str) -> None:
    with pytest.raises(IdentifierValidationError):
        ArtifactId.from_str(value)


def test_identifier_constructor_rejects_non_string_values() -> None:
    with pytest.raises(IdentifierValidationError):
        ArtifactId(123)  # type: ignore[arg-type]


def test_different_id_types_are_not_equal() -> None:
    artifact_id = ArtifactId.generate()
    requirement_id = RequirementId.generate()

    assert artifact_id != requirement_id
    assert artifact_id != str(artifact_id)


def test_ordering_is_limited_to_same_id_type() -> None:
    first = ArtifactId.from_str("ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1A")
    second = ArtifactId.from_str("ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1B")
    requirement_id = RequirementId.from_str("REQ-01HZX7M3FQ1T2Q9V8Y6K4C2B1A")

    assert first < second
    with pytest.raises(TypeError):
        first < requirement_id  # noqa: B015


def test_pydantic_parses_and_serializes_canonical_id() -> None:
    artifact_id = ArtifactId.generate()
    container = ArtifactContainer.model_validate({"artifact_id": str(artifact_id)})

    assert container.artifact_id == artifact_id
    assert container.model_dump(mode="json") == {"artifact_id": str(artifact_id)}
    assert container.model_dump_json() == f'{{"artifact_id":"{artifact_id}"}}'


def test_pydantic_rejects_cross_type_identifier() -> None:
    requirement_id = RequirementId.generate()

    with pytest.raises(ValidationError):
        ArtifactContainer.model_validate({"artifact_id": str(requirement_id)})


def test_pydantic_json_schema_contains_identifier_pattern() -> None:
    schema = ArtifactContainer.model_json_schema()
    artifact_schema = schema["properties"]["artifact_id"]

    assert artifact_schema["type"] == "string"
    assert artifact_schema["pattern"].startswith("^ART-")


def test_pydantic_union_discovers_canonical_id_type_from_string() -> None:
    requirement_id = RequirementId.generate()
    container = AnyIdContainer.model_validate({"identifier": str(requirement_id)})

    assert container.identifier == requirement_id


def test_phase_id_parses_generates_and_serializes_with_the_phs_prefix() -> None:
    phase_id = PhaseId.generate()
    container = PhaseContainer.model_validate({"phase_id": str(phase_id)})

    assert str(phase_id).startswith("PHS-")
    assert PhaseId.from_str(str(phase_id)) == phase_id
    assert container.model_dump(mode="json") == {"phase_id": str(phase_id)}
