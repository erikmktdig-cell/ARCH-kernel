"""Focused branch evidence for K10 operation semantics."""

from __future__ import annotations

import math
from typing import Any

import pytest

from arch_kernel.contracts import (
    MigrationCoercion,
    MigrationOperationType,
    MigrationPath,
    MigrationPolicy,
)
from arch_kernel.kernel.errors import ErrorCode
from arch_kernel.kernel.migration_execution import (
    _apply_operation,
    _coerce,
    _OperationError,
    _read,
    run_migration_dry_run,
)
from arch_kernel.kernel.migration_registry import MigrationRegistry
from tests.migration_helpers import (
    PayloadV1,
    PayloadV2,
    contract_registry,
    definition,
    operation,
    request,
)


@pytest.mark.parametrize(
    ("value", "coercion", "expected"),
    [
        (2, MigrationCoercion.INTEGER_TO_NUMBER, 2.0),
        (2, MigrationCoercion.INTEGER_TO_STRING, "2"),
        (2.5, MigrationCoercion.NUMBER_TO_STRING, "2.5"),
        (True, MigrationCoercion.BOOLEAN_TO_STRING, "true"),
        ("-12", MigrationCoercion.STRING_TO_INTEGER, -12),
        ("1.25e2", MigrationCoercion.STRING_TO_NUMBER, 125.0),
        ("false", MigrationCoercion.STRING_TO_BOOLEAN, False),
    ],
)
def test_closed_coercions_are_deterministic(
    value: object,
    coercion: MigrationCoercion,
    expected: object,
) -> None:
    assert _coerce(value, coercion, MigrationPath.parse("/value")) == expected


@pytest.mark.parametrize(
    ("value", "coercion"),
    [
        (True, MigrationCoercion.INTEGER_TO_NUMBER),
        (False, MigrationCoercion.INTEGER_TO_STRING),
        (True, MigrationCoercion.NUMBER_TO_STRING),
        (math.inf, MigrationCoercion.NUMBER_TO_STRING),
        (1, MigrationCoercion.BOOLEAN_TO_STRING),
        (1, MigrationCoercion.STRING_TO_INTEGER),
        ("01", MigrationCoercion.STRING_TO_INTEGER),
        ("nan", MigrationCoercion.STRING_TO_NUMBER),
        ("yes", MigrationCoercion.STRING_TO_BOOLEAN),
    ],
)
def test_closed_coercions_fail_without_guessing(
    value: object,
    coercion: MigrationCoercion,
) -> None:
    with pytest.raises(_OperationError):
        _coerce(value, coercion, MigrationPath.parse("/value"))


def test_operation_noops_and_enum_passthrough_are_explicit() -> None:
    document: dict[str, Any] = {"value": "same", "status": "unknown"}

    assert not _apply_operation(
        document,
        operation(MigrationOperationType.REPLACE, "/value", value="same"),
        enum_passthrough=False,
    )
    assert not _apply_operation(
        document,
        operation(MigrationOperationType.SET_DEFAULT, "/value", value="default"),
        enum_passthrough=False,
    )
    assert not _apply_operation(
        document,
        operation(
            MigrationOperationType.MAP_ENUM,
            "/status",
            enum_mapping={"known": "mapped"},
        ),
        enum_passthrough=True,
    )
    with pytest.raises(_OperationError):
        _apply_operation(
            document,
            operation(
                MigrationOperationType.MAP_ENUM,
                "/status",
                enum_mapping={"known": "mapped"},
            ),
            enum_passthrough=False,
        )


def test_path_failures_are_structured_and_non_mutating() -> None:
    document: dict[str, Any] = {"nested": {"value": 1}}
    before = {"nested": {"value": 1}}

    assert _read(document, MigrationPath.parse("/nested/value")) == 1
    with pytest.raises(_OperationError):
        _read(document, MigrationPath.parse("/missing/value"))
    with pytest.raises(_OperationError):
        _read(document, MigrationPath.parse("/nested/value/deeper"))
    with pytest.raises(_OperationError):
        _apply_operation(
            document,
            operation(MigrationOperationType.ADD, "/nested/value", value=2),
            enum_passthrough=False,
        )
    assert document == before


def test_registry_fingerprint_precondition_and_each_step_validation() -> None:
    contracts = contract_registry((PayloadV1, "1.0.0"), (PayloadV2, "1.1.0"))
    registry = MigrationRegistry((definition(),), contracts)
    stale = request({"name": "alpha"}).model_copy(
        update={"expected_registry_fingerprint": "sha256:" + ("0" * 64)}
    )

    failed = run_migration_dry_run(stale, registry, contracts)
    validated = run_migration_dry_run(
        request(
            {"name": "alpha"},
            policy=MigrationPolicy(validate_each_step=True),
        ),
        registry,
        contracts,
    )

    assert failed.plan is None
    assert failed.findings[0].code == ErrorCode.MIGRATION_PRECONDITION_FAILED.value
    assert validated.success
