import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from src.modules.extension_management.infra.packages.dependencies import (
    build_extension_pip_install_command,
    extension_pip_environment,
)


def test_pip_command_uses_local_wheelhouse_when_present(tmp_path: Path) -> None:
    install_root = tmp_path / "sample"
    wheelhouse = install_root / ".dvt" / "wheels"
    wheelhouse.mkdir(parents=True)

    command = build_extension_pip_install_command(
        ["demo-dep==1.0"],
        install_root=install_root,
    )

    assert "--no-index" in command
    assert "--find-links" in command
    assert str(wheelhouse) in command
    assert command[-1] == "demo-dep==1.0"


def test_offline_only_without_wheelhouse_never_uses_index(tmp_path: Path) -> None:
    command = build_extension_pip_install_command(
        ["demo-dep==1.0"],
        install_root=tmp_path / "sample",
        offline_only=True,
    )

    assert "--no-index" in command
    assert "--find-links" not in command


def test_strict_offline_pip_disables_environment_sources(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DVT_EXTENSION_OFFLINE_ONLY", "true")
    monkeypatch.setenv("PIP_FIND_LINKS", "https://unavailable.invalid/wheels")
    monkeypatch.setenv("PIP_CONSTRAINT", "https://unavailable.invalid/requirements.txt")
    command = build_extension_pip_install_command(["fixture==1.0"], install_root=tmp_path)
    assert "--no-index" in command
    assert "--only-binary=:all:" in command
    environment = extension_pip_environment()
    assert {key: value for key, value in environment.items() if key.startswith("PIP_")} == {
        "PIP_CONFIG_FILE": os.devnull,
    }


def test_strict_offline_pip_rejects_a_direct_transitive_url(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DVT_EXTENSION_OFFLINE_ONLY", "true")
    with pytest.raises(ValueError, match="named wheel dependencies"):
        build_extension_pip_install_command(
            ["direct @ https://unavailable.invalid/direct.whl"], install_root=tmp_path,
        )
    wheelhouse = tmp_path / ".dvt" / "wheels"
    wheelhouse.mkdir(parents=True)
    with ZipFile(wheelhouse / "fixture-1.0-py3-none-any.whl", "w") as archive:
        archive.writestr(
            "fixture-1.0.dist-info/METADATA",
            "Name: fixture\nVersion: 1.0\nRequires-Dist: nested @ https://unavailable.invalid/a.whl\n",
        )
    with pytest.raises(ValueError, match="named wheel dependencies"):
        build_extension_pip_install_command(["fixture==1.0"], install_root=tmp_path)
