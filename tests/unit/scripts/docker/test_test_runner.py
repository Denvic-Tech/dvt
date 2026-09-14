from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

import pytest
from scripts.docker import test_runner


def _create_extension_test_tree(
    root: Path,
    directory_name: str,
    *,
    package_name: str,
    display_name: str,
    tests_type: str = "integration",
) -> Path:
    extension_root = root / directory_name
    (extension_root / "tests" / tests_type).mkdir(parents=True)
    (extension_root / "pyproject.toml").write_text(
        "\n".join(
            (
                "[project]",
                f'name = "{package_name}"',
                "version = \"1.0.0\"",
                "",
                "[tool.dvt_extension]",
                f'name = "{package_name}"',
                f'display_name = "{display_name}"',
            )
        ),
        encoding="utf-8",
    )
    return extension_root


def test_ensure_external_docker_network_skips_creation_when_network_exists(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs) -> CompletedProcess[str]:
        calls.append(command)
        return CompletedProcess(command, 0, stdout="[]", stderr="")

    monkeypatch.setattr(test_runner.subprocess, "run", fake_run)

    test_runner.ensure_external_docker_network("dvt-net", env={"CI": "true"})

    assert calls == [["docker", "network", "inspect", "dvt-net"]]


def test_ensure_external_docker_network_creates_missing_network(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs) -> CompletedProcess[str]:
        calls.append(command)
        if command[2] == "inspect":
            return CompletedProcess(command, 1, stdout="", stderr="not found")
        return CompletedProcess(command, 0, stdout="dvt-net-id", stderr="")

    monkeypatch.setattr(test_runner.subprocess, "run", fake_run)

    test_runner.ensure_external_docker_network("dvt-net", env={"CI": "true"})

    assert calls == [
        ["docker", "network", "inspect", "dvt-net"],
        ["docker", "network", "create", "dvt-net"],
    ]


def test_resolve_test_target_returns_default_tests_dir(tmp_path: Path) -> None:
    (tmp_path / "tests" / "unit").mkdir(parents=True)

    target = test_runner.resolve_test_target(
        project_dir=tmp_path,
        tests_dir="tests/unit",
        test_path=None,
    )

    assert target == "tests/unit"


def test_resolve_test_target_accepts_file_with_pytest_node(tmp_path: Path) -> None:
    target_file = tmp_path / "tests" / "integration" / "src" / "pkg" / "test_example.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    target = test_runner.resolve_test_target(
        project_dir=tmp_path,
        tests_dir="tests/integration",
        test_path="tests/integration/src/pkg/test_example.py::test_ok",
    )

    assert target == "tests/integration/src/pkg/test_example.py::test_ok"


def test_resolve_test_target_rejects_path_outside_test_type_root(tmp_path: Path) -> None:
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    outside_file = tmp_path / "tests" / "integration" / "test_other.py"
    outside_file.parent.mkdir(parents=True)
    outside_file.write_text("def test_other():\n    assert True\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be inside 'tests/unit'"):
        test_runner.resolve_test_target(
            project_dir=tmp_path,
            tests_dir="tests/unit",
            test_path=str(outside_file.relative_to(tmp_path)),
        )


def test_collect_extension_test_dirs_rejects_legacy_duplicate_identity(tmp_path: Path) -> None:
    extensions_root = tmp_path / "extensions"
    _create_extension_test_tree(
        extensions_root,
        "Bitrix24 Connector",
        package_name="bitrix24-connector",
        display_name="Bitrix 24 Connector",
    )
    _create_extension_test_tree(
        extensions_root,
        "bitrix24-connector",
        package_name="bitrix24-connector",
        display_name="Bitrix 24 Connector",
    )

    with pytest.raises(ValueError, match="Duplicate extension test identity"):
        test_runner.collect_extension_test_dirs(
            project_dir=tmp_path,
            tests_type="integration",
            extensions_data_dir=str(extensions_root),
        )


def test_collect_extension_test_dirs_allows_same_display_name_for_distinct_packages(
    tmp_path: Path,
) -> None:
    extensions_root = tmp_path / "extensions"
    _create_extension_test_tree(
        extensions_root,
        "first-extension",
        package_name="first-extension",
        display_name="Shared Display Name",
    )
    _create_extension_test_tree(
        extensions_root,
        "second-extension",
        package_name="second-extension",
        display_name="Shared Display Name",
    )

    targets = test_runner.collect_extension_test_dirs(
        project_dir=tmp_path,
        tests_type="integration",
        extensions_data_dir=str(extensions_root),
    )

    assert targets == [
        "extensions/first-extension/tests/integration",
        "extensions/second-extension/tests/integration",
    ]


def test_resolve_extension_test_target_accepts_display_name_alias(tmp_path: Path) -> None:
    extensions_root = tmp_path / "extensions"
    _create_extension_test_tree(
        extensions_root,
        "bitrix24-connector",
        package_name="bitrix24-connector",
        display_name="Bitrix 24 Connector",
    )

    target = test_runner.resolve_extension_test_target(
        project_dir=tmp_path,
        extension_name="Bitrix 24 Connector",
        tests_type="integration",
        extensions_data_dir=str(extensions_root),
    )

    assert target == "extensions/bitrix24-connector/tests/integration"


def test_resolve_extension_test_target_rejects_ambiguous_display_name(tmp_path: Path) -> None:
    extensions_root = tmp_path / "extensions"
    _create_extension_test_tree(
        extensions_root,
        "first-extension",
        package_name="first-extension",
        display_name="Shared Display Name",
    )
    _create_extension_test_tree(
        extensions_root,
        "second-extension",
        package_name="second-extension",
        display_name="Shared Display Name",
    )

    with pytest.raises(ValueError, match="is ambiguous across test trees"):
        test_runner.resolve_extension_test_target(
            project_dir=tmp_path,
            extension_name="Shared Display Name",
            tests_type="integration",
            extensions_data_dir=str(extensions_root),
        )


def test_create_isolated_extensions_dir_creates_empty_unique_directories(tmp_path: Path) -> None:
    first = test_runner.create_isolated_extensions_dir(
        project_dir=tmp_path,
        tests_type="integration",
    )
    second = test_runner.create_isolated_extensions_dir(
        project_dir=tmp_path,
        tests_type="integration",
    )

    assert first.is_dir()
    assert second.is_dir()
    assert first != second
    assert list(first.iterdir()) == []
    assert list(second.iterdir()) == []


def test_build_prod_compose_command_includes_prod_override(tmp_path: Path) -> None:
    command = test_runner.build_prod_compose_command(tmp_path, "build", "gateway")

    assert command == [
        "docker",
        "compose",
        "--project-directory",
        str(tmp_path),
        "-f",
        "docker/docker-compose.base.yaml",
        "-f",
        "docker/docker-compose.dev.yaml",
        "-f",
        "docker/docker-compose.prod.override.yaml",
        "build",
        "gateway",
    ]
