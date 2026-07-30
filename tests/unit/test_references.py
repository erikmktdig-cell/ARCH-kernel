import pytest
from pydantic import ValidationError

from arch_kernel.contracts import (
    ArtifactId,
    EvidenceReference,
    PhaseExecutionId,
    PhaseId,
    RequirementId,
    SemanticVersion,
)
from arch_kernel.contracts.references import TypedReference

VALID_FINGERPRINT = "sha256:" + "a" * 64


def test_typed_reference_accepts_matching_target_type() -> None:
    artifact_id = ArtifactId.generate()
    version = SemanticVersion.parse("1.0.0")

    reference = TypedReference(
        target_type="artifact",
        target_id=artifact_id,
        target_version=version,
        relation="baseline",
    )

    assert reference.target_id == artifact_id
    assert reference.target_version == version
    assert reference.model_dump(mode="json") == {
        "target_type": "artifact",
        "target_id": str(artifact_id),
        "target_version": "1.0.0",
        "relation": "baseline",
    }


def test_typed_reference_detects_target_type_mismatch() -> None:
    with pytest.raises(ValidationError):
        TypedReference(target_type="requirement", target_id=ArtifactId.generate())


def test_phase_reference_rejects_phase_execution_id() -> None:
    phase_id = PhaseId.generate()
    phase_execution_id = PhaseExecutionId.generate()

    reference = TypedReference(target_type="phase", target_id=phase_id)

    assert reference.target_id == phase_id
    with pytest.raises(ValidationError):
        TypedReference(target_type="phase", target_id=phase_execution_id)


def test_phase_execution_reference_rejects_phase_id() -> None:
    phase_id = PhaseId.generate()
    phase_execution_id = PhaseExecutionId.generate()

    reference = TypedReference(target_type="phase_execution", target_id=phase_execution_id)

    assert reference.target_id == phase_execution_id
    with pytest.raises(ValidationError):
        TypedReference(target_type="phase_execution", target_id=phase_id)


def test_typed_reference_parses_id_and_version_from_json_values() -> None:
    artifact_id = ArtifactId.generate()

    reference = TypedReference.model_validate(
        {
            "target_type": "artifact",
            "target_id": str(artifact_id),
            "target_version": "1.2.3",
        }
    )

    assert reference.target_id == artifact_id
    assert reference.target_version == SemanticVersion.parse("1.2.3")


def test_evidence_reference_requires_locator() -> None:
    with pytest.raises(ValidationError):
        EvidenceReference(evidence_id=ArtifactId.generate(), evidence_type="artifact")


@pytest.mark.parametrize("field_name", ["uri", "content_ref"])
def test_evidence_reference_rejects_empty_locators(field_name: str) -> None:
    payload = {
        "evidence_id": ArtifactId.generate(),
        "evidence_type": "artifact",
        field_name: " ",
    }

    with pytest.raises(ValidationError):
        EvidenceReference.model_validate(payload)


def test_evidence_reference_rejects_invalid_fingerprint() -> None:
    with pytest.raises(ValidationError):
        EvidenceReference(
            evidence_id=ArtifactId.generate(),
            evidence_type="artifact",
            uri="https://example.test/evidence",
            fingerprint="sha256:not-hex",
        )


def test_evidence_reference_serializes_stably() -> None:
    requirement_id = RequirementId.generate()
    reference = EvidenceReference(
        evidence_id=requirement_id,
        evidence_type="requirement",
        content_ref="notion:block:abc123",
        version=SemanticVersion.parse("1.2.3+build.5"),
        fingerprint=VALID_FINGERPRINT,
        description="Approved source note",
    )

    assert reference.model_dump(mode="json") == {
        "evidence_id": str(requirement_id),
        "evidence_type": "requirement",
        "uri": None,
        "content_ref": "notion:block:abc123",
        "version": "1.2.3+build.5",
        "fingerprint": VALID_FINGERPRINT,
        "description": "Approved source note",
    }
