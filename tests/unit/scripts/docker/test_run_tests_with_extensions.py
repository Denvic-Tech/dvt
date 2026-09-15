from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

from scripts.docker import run_tests_with_extensions


def _write_extension(root: Path, name: str, tests_type: str) -> None:
    extension_root = root / name
    (extension_root / "tests" / tests_type).mkdir(parents=True)
    (extension_root / "pyproject.toml").write_text(
        "\n".join(
            (
                "[project]",
                f'name = "{name}"',
                "version = \"1.0.0\"",
                "",
                "[tool.dvt_extension]",
                f'name = "{name}"',
                f'display_name = "{name}"',
            )
        ),
        encoding="utf-8",
    )


def test_parse_args_keeps_pytest_arguments_after_separator() -> None:
    args = run_tests_with_extensions.parse_args(
        [
            "--tests-type",
            "integration",
            "--core-with-extensions",
            "--",
            "-k",
            "smoke",
            "-vv",
        ]
    )

    assert args.pytest_args == ["-k", "smoke", "-vv"]


def test_run_installs_before_discovering_extension_tests(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs) -> CompletedProcess[str]:
        commands.append(command)
        if len(commands) == 1:
            _write_extension(tmp_path, "sample-extension", "integration")
        return CompletedProcess(command, 0)

    monkeypatch.setattr(run_tests_with_extensions.subprocess, "run", fake_run)

    exit_code = run_tests_with_extensions.run(
        [
            "--tests-type",
            "integration",
            "--extensions-dir",
            str(tmp_path),
            "--core-with-extensions",
            "--",
            "-q",
        ]
    )

    assert exit_code == 0
    assert len(commands) == 2
    assert commands[0][-3:] == ["--target-dir", str(tmp_path.resolve()), "--strict"]
    assert commands[1][1:3] == ["-m", "pytest"]
    assert "tests/integration" in commands[1]
    assert "extensions/sample-extension/tests/integration" in commands[1]
    assert commands[1][-1] == "-q"
    assert list(tmp_path.iterdir()) == []


def test_run_cleans_extensions_after_install_failure(monkeypatch, tmp_path: Path) -> None:
    def fake_run(command, **_kwargs) -> CompletedProcess[str]:
        _write_extension(tmp_path, "sample-extension", "unit")
        return CompletedProcess(command, 17)

    monkeypatch.setattr(run_tests_with_extensions.subprocess, "run", fake_run)

    exit_code = run_tests_with_extensions.run(
        [
            "--tests-type",
            "unit",
            "--extensions-dir",
            str(tmp_path),
            "--core-with-extensions",
        ]
    )

    assert exit_code == 17
    assert list(tmp_path.iterdir()) == []


def test_build_test_targets_resolves_extension_after_install(tmp_path: Path) -> None:
    _write_extension(tmp_path, "sample-extension", "unit")

    targets = run_tests_with_extensions.build_test_targets(
        tests_type="unit",
        extensions_dir=str(tmp_path),
        core_target=None,
        extension_name="Sample Extension",
        include_all_extensions=False,
    )

    assert targets == ["extensions/sample-extension/tests/unit"]
