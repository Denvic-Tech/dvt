from __future__ import annotations

import tomllib
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKAGE_ROOT = _REPO_ROOT / "dvt_extension_api"


def test_extension_api_has_editable_distribution_metadata() -> None:
    pyproject = tomllib.loads((_PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["name"] == "dvt-extension-api"
    assert pyproject["project"]["version"] == "1.0.0"
    assert pyproject["tool"]["setuptools"]["package-dir"] == {"dvt_extension_api": "."}
    assert pyproject["tool"]["setuptools"]["packages"] == [
        "dvt_extension_api",
        "dvt_extension_api.v1",
    ]


def test_extension_api_distribution_covers_public_v1_modules() -> None:
    import dvt_extension_api.v1 as public_api

    v1_root = _PACKAGE_ROOT / "v1"
    assert (_PACKAGE_ROOT / "__init__.py").is_file()
    assert (v1_root / "__init__.py").is_file()
    assert all((v1_root / f"{module_name}.py").is_file() for module_name in public_api.__all__)
