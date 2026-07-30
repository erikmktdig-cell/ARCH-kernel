"""Deterministic JSON canonicalization and SHA-256 fingerprints."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from arch_kernel.kernel.time import ensure_utc

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]

_CONTENT_FINGERPRINT_EXCLUDED_FIELDS = frozenset({"created_at", "updated_at"})


def _is_canonical_id(value: object) -> bool:
    return (
        type(value).__module__ == "arch_kernel.contracts.ids"
        and hasattr(value, "prefix")
        and hasattr(value, "target_type")
        and hasattr(value, "ulid")
    )


def _is_semantic_version(value: object) -> bool:
    return (
        type(value).__module__ == "arch_kernel.contracts.versions"
        and type(value).__name__ == "SemanticVersion"
    )


def _canonical_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Canonical JSON does not permit NaN or infinite float values.")
        return value
    if isinstance(value, datetime):
        return ensure_utc(value).isoformat()
    if _is_canonical_id(value) or _is_semantic_version(value):
        return str(value)
    if isinstance(value, Enum):
        return _canonical_json_value(value.value)
    if isinstance(value, BaseModel):
        return _canonical_json_value(value.model_dump(mode="json", by_alias=False))
    if isinstance(value, Mapping):
        normalized: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Canonical JSON object keys must be strings.")
            normalized[key] = _canonical_json_value(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_canonical_json_value(item) for item in value]
    raise TypeError(f"Value of type {type(value).__name__} is not JSON canonicalizable.")


def canonicalize_json(value: object) -> bytes:
    """Serialize a supported value as canonical UTF-8 JSON bytes.

    Object keys are ordered, separators are compact, and non-finite floats are
    rejected. UTC datetimes use ISO 8601 text with the ``+00:00`` offset.
    """

    normalized = _canonical_json_value(value)
    return json.dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _normalize_exclude_fields(exclude_fields: Collection[str] | None) -> frozenset[str]:
    if exclude_fields is None:
        return frozenset()
    if isinstance(exclude_fields, str) or not all(
        isinstance(field, str) and field != "" for field in exclude_fields
    ):
        raise TypeError("exclude_fields must be a collection of non-empty field names.")
    return frozenset(exclude_fields)


def _exclude_top_level_fields(value: object, exclude_fields: frozenset[str]) -> object:
    if not exclude_fields:
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=False, exclude=set(exclude_fields))
    if isinstance(value, Mapping):
        return {key: item for key, item in value.items() if key not in exclude_fields}
    raise TypeError("exclude_fields can only be used with a Pydantic model or mapping.")


def compute_fingerprint(
    value: object,
    *,
    exclude_fields: Collection[str] | None = None,
) -> str:
    """Return the canonical SHA-256 fingerprint for ``value``.

    ``exclude_fields`` is an explicit, deterministic root-level exclusion list.
    It never removes matching names from nested objects.
    """

    excluded_fields = _normalize_exclude_fields(exclude_fields)
    fingerprint_value = _exclude_top_level_fields(value, excluded_fields)
    digest = hashlib.sha256(canonicalize_json(fingerprint_value)).hexdigest()
    return f"sha256:{digest}"


def compute_content_fingerprint(
    value: object,
    *,
    exclude_fields: Collection[str] = _CONTENT_FINGERPRINT_EXCLUDED_FIELDS,
) -> str:
    """Return a content fingerprint excluding documented root-level metadata.

    By default only ``created_at`` and ``updated_at`` are excluded. Record and
    state versions remain included unless callers explicitly add them.
    """

    return compute_fingerprint(value, exclude_fields=exclude_fields)


__all__ = ("canonicalize_json", "compute_content_fingerprint", "compute_fingerprint")
