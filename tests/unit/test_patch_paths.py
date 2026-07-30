"""Tests for canonical patch paths and segment-based scope."""

import pytest

from arch_kernel.contracts import PatchOperationType, PatchPath
from arch_kernel.kernel import ErrorCode, validate_patch_path_policy


@pytest.mark.parametrize(
    "value",
    [
        "/metadata",
        "/profile/project_type",
        "/artifacts/ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1C",
        "/dependencies/0",
    ],
)
def test_patch_path_parses_and_round_trips(value: str) -> None:
    path = PatchPath.parse(value)

    assert str(path) == value
    assert path.segments == tuple(value[1:].split("/"))
    assert hash(path) == hash(PatchPath.parse(value))


@pytest.mark.parametrize(
    "value",
    [
        "",
        "/",
        "profile/name",
        "/profile//name",
        "/profile/.",
        "/profile/..",
        "/profile\\name",
        " /profile",
        "/profile ",
        "/profile/name value",
        "/profile/~0name",
        "/profile/_private",
        "/profile/__class__",
    ],
)
def test_patch_path_rejects_noncanonical_syntax(value: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        PatchPath.parse(value)


def test_scope_matching_uses_segments_not_text_prefixes() -> None:
    scope = PatchPath.parse("/artifacts/ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1C")
    descendant = PatchPath.parse("/artifacts/ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1C/status")
    textual_prefix = PatchPath.parse("/artifacts/ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1C-extra")

    assert descendant.is_within(scope)
    assert not textual_prefix.is_within(scope)


def test_path_policy_rejects_wrong_registry_id_type() -> None:
    error = validate_patch_path_policy(
        PatchPath.parse("/artifacts/REQ-01HZX7M3FQ1T2Q9V8Y6K4C2B1D"),
        PatchOperationType.REPLACE,
    )

    assert error is not None
    assert error.code == ErrorCode.INVALID_IDENTIFIER


@pytest.mark.parametrize(
    "path",
    ["/metadata/project_id", "/artifacts/ART-01HZX7M3FQ1T2Q9V8Y6K4C2B1C/content_fingerprint"],
)
def test_path_policy_rejects_protected_fields(path: str) -> None:
    error = validate_patch_path_policy(
        PatchPath.parse(path),
        PatchOperationType.REPLACE,
    )

    assert error is not None
    assert error.code == ErrorCode.PATCH_SCOPE_VIOLATION


@pytest.mark.parametrize(
    "path",
    [
        "/decisions/DEC-01HZX7M3FQ1T2Q9V8Y6K4C2B1F/title",
        "/dependencies/0/reason",
    ],
)
def test_path_policy_rejects_internal_mutation_of_immutable_records(path: str) -> None:
    error = validate_patch_path_policy(
        PatchPath.parse(path),
        PatchOperationType.REPLACE,
    )

    assert error is not None
    assert error.code == ErrorCode.IMMUTABLE_RECORD_MODIFICATION
