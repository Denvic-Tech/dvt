from pathlib import Path

from src.modules.extension_management.infra.packages.dependencies import (
    build_extension_pip_install_command,
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
