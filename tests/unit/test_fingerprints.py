"""Tests for deterministic canonical JSON fingerprints."""

import re
from datetime import UTC, datetime, timedelta, timezone

import pytest

from arch_kernel.contracts import ArtifactId, Route, SemanticVersion
from arch_kernel.kernel import canonicalize_json, compute_content_fingerprint, compute_fingerprint


def test_canonical_json_orders_keys_and_uses_compact_separators() -> None:
    assert canonicalize_json({"z": 1, "a": [True, None]}) == b'{"a":[true,null],"z":1}'


def test_same_semantic_mapping_has_same_fingerprint_regardless_of_key_order() -> None:
    assert compute_fingerprint({"a": 1, "b": 2}) == compute_fingerprint({"b": 2, "a": 1})


def test_changed_value_has_a_different_fingerprint() -> None:
    assert compute_fingerprint({"value": 1}) != compute_fingerprint({"value": 2})


def test_explicit_exclusions_only_apply_to_root_fields() -> None:
    first = {"updated_at": "first", "nested": {"updated_at": "first"}}
    second = {"updated_at": "second", "nested": {"updated_at": "second"}}

    assert compute_fingerprint(first, exclude_fields={"updated_at"}) != compute_fingerprint(
        second, exclude_fields={"updated_at"}
    )


def test_content_fingerprint_excludes_documented_timestamp_fields() -> None:
    first = {"value": "same", "created_at": "first", "updated_at": "first"}
    second = {"value": "same", "created_at": "second", "updated_at": "second"}

    assert compute_content_fingerprint(first) == compute_content_fingerprint(second)


def test_exclusions_require_a_mapping_or_pydantic_model() -> None:
    with pytest.raises(TypeError, match="Pydantic model or mapping"):
        compute_fingerprint(["value"], exclude_fields={"updated_at"})


def test_equivalent_datetimes_normalize_to_the_same_fingerprint() -> None:
    utc_value = datetime(2026, 7, 22, 14, 30, tzinfo=UTC)
    local_value = datetime(2026, 7, 22, 8, 30, tzinfo=timezone(timedelta(hours=-6)))

    assert compute_fingerprint({"occurred_at": utc_value}) == compute_fingerprint(
        {"occurred_at": local_value}
    )
    assert (
        canonicalize_json({"occurred_at": utc_value})
        == b'{"occurred_at":"2026-07-22T14:30:00+00:00"}'
    )


def test_primitives_from_k01_serialize_stably() -> None:
    artifact_id = ArtifactId.from_str("ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1A")
    value = {
        "id": artifact_id,
        "version": SemanticVersion.parse("1.2.3-rc.1+build.7"),
        "route": Route.STANDARD,
    }

    assert canonicalize_json(value) == (
        b'{"id":"ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1A","route":"standard","version":"1.2.3-rc.1+build.7"}'
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_float_values_are_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="NaN or infinite"):
        canonicalize_json({"value": value})


def test_non_string_mapping_keys_are_rejected() -> None:
    with pytest.raises(TypeError, match="keys must be strings"):
        canonicalize_json({1: "value"})


def test_unsupported_values_are_rejected() -> None:
    with pytest.raises(TypeError, match="not JSON canonicalizable"):
        canonicalize_json({"value": {1, 2}})


def test_fingerprint_uses_the_documented_sha256_representation() -> None:
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", compute_fingerprint({"value": "demo"}))
