"""Unit tests for strict WP-K10 migration contracts."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from arch_kernel.contracts import (
    CANONICAL_ID_TYPES,
    MigrationCoercion,
    MigrationDirection,
    MigrationId,
    MigrationOperation,
    MigrationOperationType,
    MigrationPath,
    MigrationStatus,
)
from tests.migration_helpers import definition, operation, request


def test_migration_id_is_canonical_and_registered() -> None:
    migration_id = MigrationId.generate()

    assert str(migration_id).startswith("MIG-")
    assert migration_id.target_type == "migration"
    assert MigrationId in CANONICAL_ID_TYPES


@pytest.mark.parametrize(
    "value",
    ["/", "relative", "/a//b", "/a/../b", "/_private", "/a\\b", "/a/__b"],
)
def test_migration_path_rejects_unsafe_values(value: str) -> None:
    with pytest.raises((ValueError, ValidationError)):
        MigrationPath.parse(value)


def test_migration_path_round_trip_and_schema() -> None:
    path = MigrationPath.parse("/profile/display_name")

    assert str(path) == "/profile/display_name"
    assert path.segments == ("profile", "display_name")
    assert "path" in MigrationOperation.model_json_schema()["properties"]


@pytest.mark.parametrize(
    ("operation_type", "values"),
    [
        (MigrationOperationType.ADD, {"value": "x"}),
        (MigrationOperationType.REMOVE, {}),
        (MigrationOperationType.REPLACE, {"value": "x"}),
        (MigrationOperationType.MOVE, {"from_path": "/source"}),
        (MigrationOperationType.COPY, {"from_path": "/source"}),
        (MigrationOperationType.RENAME, {"from_path": "/old"}),
        (MigrationOperationType.TEST, {"expected_value": "x"}),
        (MigrationOperationType.SET_DEFAULT, {"value": None}),
        (MigrationOperationType.MAP_ENUM, {"enum_mapping": {"old": "new"}}),
        (
            MigrationOperationType.COERCE,
            {"coercion": MigrationCoercion.STRING_TO_INTEGER},
        ),
    ],
)
def test_every_operation_type_has_a_valid_shape(
    operation_type: MigrationOperationType,
    values: dict[str, object],
) -> None:
    result = operation(operation_type, "/value", **values)

    assert result.operation_type is operation_type
    assert result.model_dump(mode="json")["path"] == "/value"


@pytest.mark.parametrize(
    "raw",
    [
        {"operation_type": "add", "path": "/x"},
        {"operation_type": "remove", "path": "/x", "value": 1},
        {"operation_type": "move", "path": "/x"},
        {"operation_type": "test", "path": "/x"},
        {"operation_type": "coerce", "path": "/x"},
        {"operation_type": "map_enum", "path": "/x"},
        {
            "operation_type": "rename",
            "path": "/a/x",
            "from_path": "/b/y",
        },
    ],
)
def test_operation_rejects_incoherent_shape(raw: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        MigrationOperation.model_validate(raw)


def test_operation_json_values_are_deeply_immutable() -> None:
    item = operation(
        MigrationOperationType.ADD,
        "/nested",
        value={"items": [1, 2]},
    )
    value = item.value
    assert value is not None

    with pytest.raises(TypeError):
        value["items"] = ()  # type: ignore[index]


def test_definition_enforces_direction_and_reverse_consistency() -> None:
    current = definition()
    invalid_direction = current.model_dump()
    invalid_direction["direction"] = MigrationDirection.DOWNGRADE

    with pytest.raises(ValidationError):
        type(current).model_validate(invalid_direction)
    with pytest.raises(ValidationError):
        definition(reversible=True)


def test_definition_allows_explicit_identity_only_without_operations() -> None:
    identity = definition(operations=(), identity=True)

    assert identity.identity
    assert identity.operations == ()


def test_request_rejects_naive_time_and_duplicate_selection() -> None:
    valid = request({"name": "alpha"})
    naive = valid.model_dump()
    naive["evaluated_at"] = datetime(2026, 7, 27)

    with pytest.raises(ValidationError):
        type(valid).model_validate(naive)
    with pytest.raises(ValidationError):
        type(valid).model_validate(
            {
                **valid.model_dump(),
                "selected_migration_keys": ("migration.case_0", "migration.case_0"),
            }
        )


def test_migration_enums_are_complete() -> None:
    assert {item.value for item in MigrationStatus} == {
        "active",
        "deprecated",
        "reserved",
    }
    assert {item.value for item in MigrationDirection} == {"upgrade", "downgrade"}
    assert len(MigrationOperationType) == 10
    assert len(MigrationCoercion) == 7
