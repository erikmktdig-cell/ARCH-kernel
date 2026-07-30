"""Shared deterministic release-hardening helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
PROJECT_NAME = "arch-kernel"
PACKAGE_NAME = "arch_kernel"
SUPPORTED_PYTHONS = ("3.12", "3.13")
RELEASE_POLICY_VERSION = "1.0.0"
SOURCE_DATE_EPOCH = "1784678400"  # 2026-07-22T00:00:00Z
SECURITY_CONTACT_PLACEHOLDER = "SECURITY_CONTACT_REQUIRED"
EXPECTED_QUALITY_GATES = (
    "uv sync --all-groups",
    "uv run ruff check .",
    "uv run ruff format --check .",
    "uv run mypy src tests scripts",
    "uv run pytest",
    "uv run pytest -m property",
    "uv run pytest -m regression",
    "uv run pytest -m release",
    "uv run pytest -p no:cacheprovider",
    "git diff --check",
    "uv build",
    "uv run python scripts/check_artifacts.py dist",
    "uv run python scripts/check_reproducible_build.py",
    "uv run python scripts/check_release.py",
)
PROHIBITED_ARCHIVE_PARTS = (
    ".git",
    ".pytest_cache",
    ".hypothesis",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    ".coverage",
    ".env",
    "dist",
)
ALLOWED_LICENSE_TOKENS = (
    "apache",
    "bsd",
    "isc",
    "mit",
    "mozilla public license 2.0",
    "mpl-2.0",
    "psf",
    "python software foundation",
    "unlicense",
)
DENIED_LICENSE_TOKENS = (
    "agpl",
    "gnu affero",
)


class ReleaseCheckError(RuntimeError):
    """A deterministic, user-facing release gate failure."""


@dataclass(frozen=True)
class CommandResult:
    """Captured command result."""

    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def canonical_json_bytes(value: object) -> bytes:
    """Serialize stable evidence using one canonical JSON representation."""

    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def sha256_bytes(value: bytes) -> str:
    """Return a prefixed SHA-256 digest."""

    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def sha256_file(path: Path) -> str:
    """Hash one file without platform newline conversion."""

    return sha256_bytes(path.read_bytes())


def read_json(path: Path) -> Any:
    """Read a UTF-8 JSON file."""

    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    """Write deterministic UTF-8 JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def package_version(root: Path = ROOT) -> str:
    """Read the single authoritative static package version."""

    text = (root / "src" / PACKAGE_NAME / "__about__.py").read_text(encoding="utf-8")
    match = re.fullmatch(
        r'"""Authoritative package version\."""\s+__version__ = "([^"]+)"\s*',
        text,
    )
    if match is None:
        raise ReleaseCheckError("cannot read canonical version from __about__.py")
    version = match.group(1)
    if (
        re.fullmatch(
            r"(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*)){2}(?:[a-z]+\d+)?",
            version,
        )
        is None
    ):
        raise ReleaseCheckError(f"package version is not accepted PEP 440 form: {version}")
    return version


def project_metadata(root: Path = ROOT) -> Mapping[str, Any]:
    """Load project metadata from pyproject."""

    with (root / "pyproject.toml").open("rb") as handle:
        return cast(Mapping[str, Any], tomllib.load(handle)["project"])


def expected_artifact_names(root: Path = ROOT) -> tuple[str, str]:
    """Return canonical sdist and pure-Python wheel filenames."""

    version = package_version(root)
    return (
        f"arch_kernel-{version}.tar.gz",
        f"arch_kernel-{version}-py3-none-any.whl",
    )


def fingerprint_json_member(path: Path, member: str | None = None) -> str:
    """Fingerprint all or one member of a JSON document canonically."""

    payload = read_json(path)
    if member is not None:
        payload = payload[member]
    return sha256_bytes(canonical_json_bytes(payload))


def stable_release_manifest(root: Path = ROOT) -> dict[str, Any]:
    """Build the stable, source-controlled release manifest."""

    schema_manifest = read_json(root / "schemas" / "manifest.json")
    fixture_manifest = read_json(root / "fixtures" / "manifest.json")
    public_snapshot = read_json(
        root / "tests" / "regression" / "snapshots" / "public_contracts.json"
    )
    sdist, wheel = expected_artifact_names(root)
    return {
        "manifest_format_version": "1.0.0",
        "release_policy_version": RELEASE_POLICY_VERSION,
        "project_name": PROJECT_NAME,
        "package_version": package_version(root),
        "version_source": "src/arch_kernel/__about__.py",
        "supported_python_versions": list(SUPPORTED_PYTHONS),
        "build_backend": {
            "name": "hatchling.build",
            "requirement": "hatchling>=1.27",
        },
        "quality_gate_commands": list(EXPECTED_QUALITY_GATES),
        "expected_artifacts": {
            "sdist": sdist,
            "wheel": wheel,
            "hashes": {"sdist": None, "wheel": None},
        },
        "fingerprints": {
            "contract_catalog": schema_manifest["catalog_fingerprint"],
            "fixture_manifest": fixture_manifest["manifest_fingerprint"],
            "schema_manifest": fingerprint_json_member(root / "schemas" / "manifest.json"),
            "public_api_snapshot": public_snapshot["snapshot_fingerprint"],
            "error_code_snapshot": fingerprint_json_member(
                root / "tests" / "regression" / "snapshots" / "public_contracts.json",
                "error_codes",
            ),
            "dependency_lock": sha256_file(root / "uv.lock"),
        },
        "coverage": {"branch_threshold_percent": 90, "observed_percent": None},
        "test_counts": {},
        "source_commit": None,
        "candidate_evidence": "dist/release-evidence.json",
    }


def compare_generated(expected: Path, generated: bytes) -> None:
    """Fail when a committed deterministic artifact is stale."""

    current = expected.read_bytes()
    if current != generated:
        raise ReleaseCheckError(f"stale generated artifact: {expected.relative_to(ROOT)}")


def run_command(
    command: Sequence[str],
    *,
    cwd: Path = ROOT,
    env: Mapping[str, str] | None = None,
    check: bool = True,
) -> CommandResult:
    """Run one platform-neutral command with captured output."""

    completed = subprocess.run(
        command,
        cwd=cwd,
        env=dict(env) if env is not None else None,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    result = CommandResult(
        command=tuple(command),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    if check and result.returncode:
        detail = (result.stdout + result.stderr).strip()
        raise ReleaseCheckError(f"command failed ({' '.join(command)}):\n{detail}")
    return result


def normalized_build_environment() -> dict[str, str]:
    """Return an archive-stable build environment."""

    environment = dict(os.environ)
    environment.update(
        {
            "SOURCE_DATE_EPOCH": SOURCE_DATE_EPOCH,
            "PYTHONHASHSEED": "0",
            "TZ": "UTC",
            "LC_ALL": "C.UTF-8" if os.name != "nt" else "C",
        }
    )
    return environment


def safe_archive_name(name: str) -> PurePosixPath:
    """Validate and normalize one archive member name."""

    if "\\" in name:
        raise ReleaseCheckError(f"archive member uses non-POSIX separator: {name}")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ReleaseCheckError(f"unsafe archive member path: {name}")
    if any(part in PROHIBITED_ARCHIVE_PARTS for part in path.parts):
        raise ReleaseCheckError(f"prohibited archive member: {name}")
    return path


def zip_members(path: Path) -> tuple[str, ...]:
    """Return validated ZIP member names."""

    with zipfile.ZipFile(path) as archive:
        names = tuple(item.filename for item in archive.infolist())
        if len(names) != len(set(names)):
            raise ReleaseCheckError(f"duplicate archive members in {path.name}")
        for name in names:
            safe_archive_name(name)
        bad = archive.testzip()
        if bad is not None:
            raise ReleaseCheckError(f"corrupt ZIP member in {path.name}: {bad}")
    return names


def tar_members(path: Path) -> tuple[str, ...]:
    """Return validated TAR member names."""

    with tarfile.open(path, "r:gz") as archive:
        names = tuple(item.name for item in archive.getmembers())
        if len(names) != len(set(names)):
            raise ReleaseCheckError(f"duplicate archive members in {path.name}")
        for item in archive.getmembers():
            safe_archive_name(item.name)
            if item.issym() or item.islnk():
                raise ReleaseCheckError(f"links are not allowed in sdist: {item.name}")
    return names


def inspect_distributions(dist_dir: Path) -> dict[str, Any]:
    """Inspect wheel and sdist names, metadata, contents, and hashes."""

    dist_dir = dist_dir.resolve()
    expected_sdist, expected_wheel = expected_artifact_names()
    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if [path.name for path in wheels] != [expected_wheel]:
        raise ReleaseCheckError(
            f"expected exactly {expected_wheel}; found {[p.name for p in wheels]}"
        )
    if [path.name for path in sdists] != [expected_sdist]:
        raise ReleaseCheckError(
            f"expected exactly {expected_sdist}; found {[p.name for p in sdists]}"
        )
    wheel = wheels[0]
    sdist = sdists[0]
    wheel_names = zip_members(wheel)
    sdist_names = tar_members(sdist)
    required_wheel = {
        "arch_kernel/__init__.py",
        "arch_kernel/__about__.py",
        "arch_kernel/py.typed",
        "arch_kernel/schemas/manifest.json",
    }
    missing_wheel = sorted(required_wheel.difference(wheel_names))
    if missing_wheel:
        raise ReleaseCheckError(f"wheel is missing required members: {missing_wheel}")
    if not any(name.startswith("arch_kernel/schemas/contracts/") for name in wheel_names):
        raise ReleaseCheckError("wheel contains no published contract schemas")
    root = f"arch_kernel-{package_version()}"
    required_sdist = {
        f"{root}/LICENSE",
        f"{root}/README.md",
        f"{root}/pyproject.toml",
        f"{root}/schemas/manifest.json",
        f"{root}/src/arch_kernel/py.typed",
    }
    missing_sdist = sorted(required_sdist.difference(sdist_names))
    if missing_sdist:
        raise ReleaseCheckError(f"sdist is missing required members: {missing_sdist}")
    metadata_name = next(
        (name for name in wheel_names if name.endswith(".dist-info/METADATA")),
        None,
    )
    if metadata_name is None:
        raise ReleaseCheckError("wheel metadata is missing")
    with zipfile.ZipFile(wheel) as archive:
        metadata = archive.read(metadata_name).decode()
    expected_headers = (
        f"Name: {PROJECT_NAME}",
        f"Version: {package_version()}",
        "Requires-Python: <3.14,>=3.12",
    )
    for header in expected_headers:
        if header not in metadata:
            raise ReleaseCheckError(f"wheel metadata is missing {header!r}")
    schema_members = [
        name for name in wheel_names if name.startswith("arch_kernel/schemas/contracts/")
    ]
    if schema_members != sorted(schema_members):
        raise ReleaseCheckError("wheel contract-schema members are not deterministically ordered")
    return {
        "artifacts": {
            "wheel": {"filename": wheel.name, "sha256": sha256_file(wheel)},
            "sdist": {"filename": sdist.name, "sha256": sha256_file(sdist)},
        },
        "members": {"wheel": len(wheel_names), "sdist": len(sdist_names)},
    }


def isolated_install_smoke(dist_dir: Path) -> None:
    """Install the wheel offline and exercise representative public behavior."""

    dist_dir = dist_dir.resolve()
    wheel = dist_dir / expected_artifact_names()[1]
    with tempfile.TemporaryDirectory(prefix="arch-kernel-smoke-") as temp_name:
        temp = Path(temp_name)
        venv = temp / "venv"
        run_command((sys.executable, "-m", "venv", str(venv)), cwd=temp)
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        import pydantic

        dependency_site = Path(pydantic.__file__).resolve().parents[1]
        purelib_result = run_command(
            (
                str(python),
                "-c",
                "import sysconfig; print(sysconfig.get_path('purelib'))",
            ),
            cwd=temp,
        )
        purelib = Path(purelib_result.stdout.strip())
        (purelib / "arch-kernel-locked-dependencies.pth").write_text(
            f"{dependency_site}\n",
            encoding="utf-8",
            newline="\n",
        )
        uv = shutil.which("uv")
        if uv is None:
            raise ReleaseCheckError("uv is required for the isolated installation smoke test")
        run_command(
            (
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                "--offline",
                "--no-deps",
                str(wheel),
            ),
            cwd=temp,
        )
        state = ROOT / "fixtures" / "valid" / "minimal_project_state.json"
        patch = ROOT / "fixtures" / "valid" / "state_patch" / "replace_project_profile.json"
        smoke = temp / "smoke.py"
        smoke.write_text(
            """
import importlib.metadata
import importlib.resources
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import arch_kernel
from arch_kernel.contracts import (
    ProjectState,
    StatePatch,
    ValidationIntent,
    ValidationPipelineRequest,
)
from arch_kernel.kernel import (
    apply_state_patch_dry_run,
    build_builtin_contract_registry,
    generate_registry_schemas,
    run_validation_pipeline,
)

root = Path(arch_kernel.__file__).resolve()
for forbidden in json.loads(os.environ["FORBIDDEN_IMPORT_ROOTS"]):
    assert not root.is_relative_to(Path(forbidden).resolve())
assert arch_kernel.__version__ == importlib.metadata.version("arch-kernel")
registry = build_builtin_contract_registry()
assert len(registry.registrations) == 35
assert len(generate_registry_schemas(registry)) == 35
schema_root = importlib.resources.files("arch_kernel.schemas")
assert schema_root.joinpath("manifest.json").is_file()
state = ProjectState.model_validate_json(Path(os.environ["STATE_FIXTURE"]).read_text())
patch = StatePatch.model_validate_json(Path(os.environ["PATCH_FIXTURE"]).read_text())
dry_run = apply_state_patch_dry_run(state, patch)
assert dry_run.validation.is_valid and dry_run.projected_state is not None
request = ValidationPipelineRequest.model_validate({
    "intent": ValidationIntent.VALIDATE_STATE,
    "evaluated_at": datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
    "state": state.model_dump(mode="json"),
})
assert run_validation_pipeline(request).success
""".lstrip(),
            encoding="utf-8",
            newline="\n",
        )
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.update(
            {
                "FORBIDDEN_IMPORT_ROOTS": json.dumps(
                    [str(ROOT), str(ROOT / "src"), str(ROOT / ".venv")]
                ),
                "STATE_FIXTURE": str(state),
                "PATCH_FIXTURE": str(patch),
                "PYTHONNOUSERSITE": "1",
            }
        )
        run_command((str(python), "-I", str(smoke)), cwd=temp, env=environment)


def copy_release_source(destination: Path) -> None:
    """Copy only release-relevant source into a clean build tree."""

    included = (
        ".python-version",
        "LICENSE",
        "README.md",
        "pyproject.toml",
        "schemas",
        "src",
    )
    for name in included:
        source = ROOT / name
        target = destination / name
        if source.is_dir():
            shutil.copytree(
                source,
                target,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        else:
            shutil.copy2(source, target)


def semantic_archive_members(path: Path) -> dict[str, str]:
    """Map normalized archive members to content digests."""

    result: dict[str, str] = {}
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                normalized = re.sub(r"^arch_kernel-[^/]+", "arch_kernel-VERSION", name)
                result[normalized] = sha256_bytes(archive.read(name))
    else:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                normalized = re.sub(r"^arch_kernel-[^/]+", "arch_kernel-VERSION", member.name)
                result[normalized] = sha256_bytes(handle.read())
    return result


def dependency_inventory() -> list[dict[str, str]]:
    """Return installed dependency license metadata in stable order."""

    from importlib.metadata import distributions

    inventory: list[dict[str, str]] = []
    for distribution in distributions():
        name = distribution.metadata.get("Name")
        if not name:
            continue
        license_value = (
            distribution.metadata.get("License-Expression")
            or distribution.metadata.get("License")
            or ""
        ).strip()
        if not license_value:
            classifiers = distribution.metadata.get_all("Classifier") or []
            license_value = "; ".join(
                item.removeprefix("License :: ").strip()
                for item in classifiers
                if item.startswith("License :: ")
            )
        inventory.append(
            {
                "name": name,
                "version": distribution.version,
                "license": license_value or "UNKNOWN",
            }
        )
    return sorted(inventory, key=lambda item: item["name"].casefold())


def evaluate_license_policy(
    inventory: Iterable[Mapping[str, str]],
) -> dict[str, list[dict[str, str]]]:
    """Classify metadata only; this is not a legal conclusion."""

    result: dict[str, list[dict[str, str]]] = {
        "allowed": [],
        "denied": [],
        "manual_review": [],
    }
    for raw_item in inventory:
        item = dict(raw_item)
        value = item["license"].casefold()
        if any(token in value for token in DENIED_LICENSE_TOKENS):
            result["denied"].append(item)
        elif any(token in value for token in ALLOWED_LICENSE_TOKENS):
            result["allowed"].append(item)
        else:
            result["manual_review"].append(item)
    return result


def release_environment_blockers(root: Path = ROOT) -> list[str]:
    """Return unresolved owner-controlled release governance items."""

    security = (root / "SECURITY.md").read_text(encoding="utf-8")
    blockers: list[str] = []
    if SECURITY_CONTACT_PLACEHOLDER in security:
        blockers.append("a real private security-reporting contact is not configured")
    return blockers


__all__ = (
    "EXPECTED_QUALITY_GATES",
    "PROJECT_NAME",
    "RELEASE_POLICY_VERSION",
    "ROOT",
    "SECURITY_CONTACT_PLACEHOLDER",
    "SOURCE_DATE_EPOCH",
    "SUPPORTED_PYTHONS",
    "ReleaseCheckError",
    "canonical_json_bytes",
    "compare_generated",
    "copy_release_source",
    "dependency_inventory",
    "evaluate_license_policy",
    "expected_artifact_names",
    "inspect_distributions",
    "isolated_install_smoke",
    "normalized_build_environment",
    "package_version",
    "project_metadata",
    "read_json",
    "release_environment_blockers",
    "run_command",
    "semantic_archive_members",
    "sha256_file",
    "stable_release_manifest",
    "write_json",
)
