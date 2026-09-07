"""Shared distribution fixtures for release tests."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from scripts.release_common import ROOT, SOURCE_DATE_EPOCH


@pytest.fixture(scope="session")
def built_dist() -> Path:
    """Build one candidate distribution for direct archive tests."""

    dist = ROOT / "dist"
    if dist.exists():
        shutil.rmtree(dist)
    environment = dict(os.environ)
    environment["SOURCE_DATE_EPOCH"] = SOURCE_DATE_EPOCH
    subprocess.run(
        ("uv", "build", "--offline"),
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return dist
