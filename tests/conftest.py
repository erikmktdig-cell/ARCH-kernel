"""Shared pytest and Hypothesis configuration for WP-K11."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

import pytest
from hypothesis import HealthCheck, settings

settings.register_profile(
    "local",
    max_examples=25,
    deadline=None,
    print_blob=True,
)
settings.register_profile(
    "ci",
    max_examples=100,
    deadline=None,
    print_blob=True,
    suppress_health_check=(HealthCheck.too_slow,),
)
settings.register_profile(
    "debug",
    max_examples=10,
    deadline=None,
    print_blob=True,
    database=None,
)
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "local"))


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    """Reserve the global coverage threshold for complete-suite runs."""

    if config.option.markexpr in {"property", "regression", "release"} and hasattr(
        config.option, "cov_fail_under"
    ):
        config.option.cov_fail_under = 0
        coverage_plugin = config.pluginmanager.get_plugin("_cov")
        if coverage_plugin is not None:
            cast(Any, coverage_plugin).options.cov_fail_under = 0


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply stable suite markers from filesystem ownership."""

    for item in items:
        path = Path(str(item.path)).as_posix()
        if "/tests/unit/" in f"/{path}":
            item.add_marker(pytest.mark.unit)
        elif "/tests/contract/" in f"/{path}":
            item.add_marker(pytest.mark.contract)
        elif "/tests/property/" in f"/{path}":
            item.add_marker(pytest.mark.property)
        elif "/tests/regression/" in f"/{path}":
            item.add_marker(pytest.mark.regression)
        elif "/tests/release/" in f"/{path}":
            item.add_marker(pytest.mark.release)
