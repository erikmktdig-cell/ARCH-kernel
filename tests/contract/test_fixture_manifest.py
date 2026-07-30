"""Canonical manifest conformance tests for every JSON fixture."""

from __future__ import annotations

import json

from scripts.build_fixture_manifest import build_manifest

from arch_kernel.kernel.fingerprints import compute_fingerprint
from tests.fixture_catalog import load_fixture, load_manifest


def test_manifest_is_complete_unique_ordered_and_fingerprint_valid() -> None:
    entries = load_manifest()

    assert entries
    assert tuple(item.key for item in entries) == tuple(sorted(item.key for item in entries))
    assert len({item.key for item in entries}) == len(entries)
    assert len({item.path for item in entries}) == len(entries)


def test_loader_returns_detached_fingerprint_stable_payloads() -> None:
    for metadata in load_manifest():
        first = load_fixture(metadata)
        second = load_fixture(metadata)
        assert first is not second, metadata.key
        assert compute_fingerprint(first) == metadata.payload_fingerprint
        if isinstance(first, dict):
            first["_k11_detached_probe"] = True
            assert isinstance(second, dict)
            assert "_k11_detached_probe" not in second, metadata.key
        else:
            first.append("_k11_detached_probe")
            assert isinstance(second, list)
            assert "_k11_detached_probe" not in second, metadata.key


def test_manifest_generation_is_side_effect_free_and_deterministic() -> None:
    first = build_manifest()
    second = build_manifest()

    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_no_fixture_contains_machine_specific_user_paths() -> None:
    forbidden = ("C:\\Users\\", "/Users/", "/home/")
    for metadata in load_manifest():
        text = json.dumps(load_fixture(metadata), ensure_ascii=False)
        assert not any(token in text for token in forbidden), metadata.key
