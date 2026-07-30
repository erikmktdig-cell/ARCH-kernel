from importlib.metadata import version
from importlib.util import find_spec
from pathlib import Path

import arch_kernel


def test_package_imports() -> None:
    assert arch_kernel.__name__ == "arch_kernel"


def test_package_version() -> None:
    assert arch_kernel.__version__ == "0.1.0"
    assert version("arch-kernel") == arch_kernel.__version__


def test_public_exports_only_version() -> None:
    assert arch_kernel.__all__ == ("__version__",)


def test_package_is_discovered_from_src_layout() -> None:
    spec = find_spec("arch_kernel")

    assert spec is not None
    assert spec.origin is not None

    origin = Path(spec.origin)
    assert origin.name == "__init__.py"
    assert origin.parent.name == "arch_kernel"
    assert origin.parent.parent.name == "src"
