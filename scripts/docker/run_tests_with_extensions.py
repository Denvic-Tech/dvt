from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from scripts.docker.test_runner import (
        PROJECT_DIR,
        collect_extension_test_dirs,
        resolve_extension_test_target,
    )
except ModuleNotFoundError:
    from test_runner import (  # type: ignore[no-redef]
        PROJECT_DIR,
        collect_extension_test_dirs,
        resolve_extension_test_target,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install extensions into the tester volume, discover their tests, and run pytest."
    )
    parser.add_argument(
        "--tests-type",
        required=True,
        choices=("unit", "integration", "e2e"),
    )
    parser.add_argument(
        "--extensions-dir",
        default="/app/extensions",
        help="Extension directory inside the tester container.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--core-target",
        help="Run one already-resolved core test target and do not collect extension tests.",
    )
    mode.add_argument(
        "--extension",
        help="Run tests for one extension after the extension set has been installed.",
    )
    mode.add_argument(
        "--core-with-extensions",
        action="store_true",
        help="Run the complete core test directory plus all installed extension test directories.",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Additional pytest arguments. Prefix them with '--' to stop wrapper option parsing.",
    )
    args = parser.parse_args(argv)
    if args.pytest_args[:1] == ["--"]:
        args.pytest_args = args.pytest_args[1:]
    return args


def build_test_targets(
    *,
    tests_type: str,
    extensions_dir: str,
    core_target: str | None,
    extension_name: str | None,
    include_all_extensions: bool,
) -> list[str]:
    if core_target is not None:
        return [core_target]

    if extension_name is not None:
        return [
            resolve_extension_test_target(
                project_dir=PROJECT_DIR,
                extension_name=extension_name,
                tests_type=tests_type,
                extensions_data_dir=extensions_dir,
            )
        ]

    if not include_all_extensions:
        raise ValueError("No test selection mode was configured")

    test_targets = [f"tests/{tests_type}"]
    extension_dirs = collect_extension_test_dirs(
        project_dir=PROJECT_DIR,
        tests_type=tests_type,
        extensions_data_dir=extensions_dir,
    )
    if extension_dirs:
        print(f"Найдены тесты расширений: {', '.join(extension_dirs)}")
    test_targets.extend(extension_dirs)
    return test_targets


def cleanup_extensions_dir_contents(extensions_dir: Path) -> None:
    """Remove tester-created files while still running with the container's ownership privileges."""
    if not extensions_dir.exists():
        return
    for entry in extensions_dir.iterdir():
        if entry.is_symlink() or entry.is_file():
            entry.unlink()
        else:
            shutil.rmtree(entry)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    extensions_dir = Path(args.extensions_dir).resolve()

    try:
        install_command = [
            sys.executable,
            "scripts/docker/install_extensions_locally.py",
            "--target-dir",
            str(extensions_dir),
            "--strict",
        ]
        install_result = subprocess.run(install_command, cwd=PROJECT_DIR, check=False)
        if install_result.returncode != 0:
            return install_result.returncode

        try:
            test_targets = build_test_targets(
                tests_type=args.tests_type,
                extensions_dir=str(extensions_dir),
                core_target=args.core_target,
                extension_name=args.extension,
                include_all_extensions=args.core_with_extensions,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2

        pytest_command = [
            sys.executable,
            "-m",
            "pytest",
            *test_targets,
            *args.pytest_args,
        ]
        return subprocess.run(pytest_command, cwd=PROJECT_DIR, check=False).returncode
    finally:
        cleanup_extensions_dir_contents(extensions_dir)


if __name__ == "__main__":
    sys.exit(run())
