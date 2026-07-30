"""Tests for the strict base Pydantic contract models."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import ContractModel, ImmutableRecord, SemanticVersion, VersionedRecord


class ExampleContract(ContractModel):
    value: str


class ExampleVersionedRecord(VersionedRecord):
    value: str


class ExampleImmutableRecord(ImmutableRecord):
    values: list[str]


def _base_fields() -> dict[str, object]:
    return {
        "contract_name": "example_contract",
        "contract_version": SemanticVersion.parse("1.0.0"),
        "schema_uri": "urn:arch:contracts:example_contract:1.0.0",
        "created_at": datetime(2026, 7, 22, 14, 30, tzinfo=UTC),
    }


def _example_contract(**values: object) -> ExampleContract:
    return ExampleContract.model_validate({**_base_fields(), **values})


def _versioned_record(**values: object) -> ExampleVersionedRecord:
    return ExampleVersionedRecord.model_validate({**_base_fields(), **values})


def _immutable_record(**values: object) -> ExampleImmutableRecord:
    return ExampleImmutableRecord.model_validate({**_base_fields(), **values})


def test_contract_model_accepts_valid_values() -> None:
    contract = _example_contract(value="demo")

    assert contract.value == "demo"
    assert contract.updated_at is None


def test_contract_model_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _example_contract(value="demo", unexpected="no")


@pytest.mark.parametrize("field_name", ["contract_name", "schema_uri"])
def test_contract_model_rejects_blank_metadata(field_name: str) -> None:
    fields = _base_fields()
    fields[field_name] = "   "

    with pytest.raises(ValidationError, match=f"{field_name} cannot be empty"):
        _example_contract(**fields, value="demo")


def test_contract_model_rejects_naive_datetimes() -> None:
    fields = _base_fields()
    fields["created_at"] = datetime(2026, 7, 22, 14, 30)

    with pytest.raises(ValidationError, match="Naive datetimes"):
        _example_contract(**fields, value="demo")


def test_contract_model_normalizes_timestamps_to_utc() -> None:
    fields = _base_fields()
    fields["created_at"] = datetime(2026, 7, 22, 8, 30, tzinfo=timezone(timedelta(hours=-6)))

    contract = _example_contract(**fields, value="demo")

    assert contract.created_at == datetime(2026, 7, 22, 14, 30, tzinfo=UTC)
    assert contract.created_at.tzinfo is UTC


def test_contract_model_rejects_updated_at_before_created_at() -> None:
    fields = _base_fields()
    fields["updated_at"] = datetime(2026, 7, 22, 14, 29, tzinfo=UTC)

    with pytest.raises(ValidationError, match="updated_at must be greater"):
        _example_contract(**fields, value="demo")


def test_contract_model_assignments_are_validated() -> None:
    contract = _example_contract(value="demo")

    with pytest.raises(ValidationError):
        contract.updated_at = datetime(2026, 7, 22, 14, 29)


def test_contract_model_round_trips_canonical_json() -> None:
    contract = _example_contract(value="demo")

    restored = ExampleContract.model_validate_json(contract.canonical_json())

    assert restored == contract
    assert restored.canonical_dict() == contract.canonical_dict()


def test_contract_model_fingerprint_includes_all_serialized_fields() -> None:
    contract = _example_contract(value="first")
    updated = _example_contract(
        value="first",
        updated_at=datetime(2026, 7, 22, 14, 31, tzinfo=UTC),
    )

    assert contract.fingerprint() != updated.fingerprint()
    assert contract.record_fingerprint() == contract.fingerprint()


def test_contract_model_content_fingerprint_ignores_updated_at() -> None:
    first = _example_contract(
        value="same",
        updated_at=datetime(2026, 7, 22, 14, 31, tzinfo=UTC),
    )
    second = _example_contract(
        value="same",
        updated_at=datetime(2026, 7, 22, 14, 32, tzinfo=UTC),
    )

    assert first.contract_content_fingerprint() == second.contract_content_fingerprint()


def test_contract_model_content_fingerprint_detects_contractual_changes() -> None:
    first = _example_contract(
        value="first",
        updated_at=datetime(2026, 7, 22, 14, 31, tzinfo=UTC),
    )
    second = _example_contract(
        value="second",
        updated_at=datetime(2026, 7, 22, 14, 32, tzinfo=UTC),
    )

    assert first.contract_content_fingerprint() != second.contract_content_fingerprint()


def test_contract_model_schema_exposes_base_requirements() -> None:
    schema = ExampleContract.model_json_schema()

    assert {"contract_name", "contract_version", "schema_uri", "created_at"} <= set(
        schema["required"]
    )
    assert schema["additionalProperties"] is False


def test_versioned_record_accepts_valid_versions() -> None:
    record = _versioned_record(
        value="demo",
        record_version=1,
        state_version_created=0,
        state_version_updated=3,
    )

    assert record.record_version == 1


@pytest.mark.parametrize(
    ("field_name", "value"),
    [("record_version", 0), ("state_version_created", -1), ("state_version_updated", -1)],
)
def test_versioned_record_rejects_invalid_non_negative_versions(
    field_name: str, value: int
) -> None:
    fields = {
        **_base_fields(),
        "value": "demo",
        "record_version": 1,
        "state_version_created": 0,
        "state_version_updated": 0,
    }
    fields[field_name] = value

    with pytest.raises(ValidationError):
        _versioned_record(**fields)


def test_versioned_record_rejects_state_version_regression() -> None:
    with pytest.raises(ValidationError, match="state_version_updated must be greater"):
        _versioned_record(
            value="demo",
            record_version=1,
            state_version_created=2,
            state_version_updated=1,
        )


def test_immutable_record_rejects_field_reassignment_and_remains_fingerprintable() -> None:
    record = _immutable_record(values=["first"])

    with pytest.raises(ValidationError, match="Instance is frozen"):
        record.values = ["second"]

    assert record.fingerprint().startswith("sha256:")


def test_immutable_record_does_not_claim_deep_immutability() -> None:
    record = _immutable_record(values=["first"])

    record.values.append("second")

    assert record.values == ["first", "second"]
