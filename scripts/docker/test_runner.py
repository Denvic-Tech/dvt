from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
import tomllib
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
_TEST_COMPOSE_FILES = (
    "docker/docker-compose.base.yaml",
    "docker/docker-compose.dev.yaml",
    "docker/docker-compose.tests.yaml",
)
_APP_COMPOSE_FILES = (
    "docker/docker-compose.base.yaml",
    "docker/docker-compose.dev.yaml",
)
_PROD_COMPOSE_FILES = (
    "docker/docker-compose.base.yaml",
    "docker/docker-compose.dev.yaml",
    "docker/docker-compose.prod.override.yaml",
)


def run_command(
    command: list[str],
    *,
    env: dict[str, str],
    extra_env: dict[str, str] | None = None,
) -> int:
    command_env = env.copy()
    if extra_env:
        command_env.update(extra_env)
    result = subprocess.run(command, env=command_env)
    return result.returncode


def ensure_external_docker_network(name: str, *, env: dict[str, str]) -> None:
    inspect_result = subprocess.run(
        ["docker", "network", "inspect", name],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if inspect_result.returncode == 0:
        print(f"Docker network '{name}' already exists")
        return
    if inspect_result.returncode != 1:
        raise RuntimeError(
            f"Unable to inspect Docker network '{name}': "
            f"{inspect_result.stderr.strip() or inspect_result.stdout.strip()}"
        )

    print(f"Creating Docker network: {name}")
    create_result = subprocess.run(
        ["docker", "network", "create", name],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if create_result.returncode == 0:
        return

    # A parallel CI job may have created the network after the inspect call.
    retry_inspect_result = subprocess.run(
        ["docker", "network", "inspect", name],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if retry_inspect_result.returncode == 0:
        print(f"Docker network '{name}' was created concurrently")
        return

    raise RuntimeError(
        f"Unable to create Docker network '{name}': "
        f"{create_result.stderr.strip() or create_result.stdout.strip()}"
    )


def parse_test_script_args(argv: list[str] | None = None) -> tuple[str | None, list[str], str | None]:
    parser = argparse.ArgumentParser(
        description="Run dockerized tests with optional targeted test path."
    )
    parser.add_argument(
        "test_path",
        nargs="?",
        default=None,
        help="Optional test file/directory path (or pytest node id with ::) inside the test type root.",
    )
    parser.add_argument(
        "-e",
        "--extension",
        default=None,
        help="Run tests for the named extension only.",
    )
    args, pytest_args = parser.parse_known_args(argv)
    return args.test_path, pytest_args, args.extension


_EXTENSION_IDENTITY_SEPARATOR_RE = re.compile(r"[-_.\s]+")


def create_isolated_extensions_dir(*, project_dir: Path, tests_type: str) -> Path:
    """Create a per-run host directory used as the tester's /app/extensions bind mount."""
    root = project_dir / "tmp" / "test-extensions"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{tests_type}-", dir=root))


def _normalize_extension_test_identity(value: str) -> str:
    return _EXTENSION_IDENTITY_SEPARATOR_RE.sub("-", value.strip().lower()).strip("-")


def _extension_test_names(entry: Path) -> tuple[set[str], set[str]]:
    """Return canonical identities and broader lookup aliases for an extension test tree."""
    identities = {entry.name}
    aliases = {entry.name}
    pyproject_path = entry / "pyproject.toml"
    if pyproject_path.is_file():
        try:
            payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            payload = {}
        project = payload.get("project")
        if isinstance(project, dict) and isinstance(project.get("name"), str):
            identities.add(project["name"])
            aliases.add(project["name"])
        tool = payload.get("tool")
        dvt_extension = tool.get("dvt_extension") if isinstance(tool, dict) else None
        if isinstance(dvt_extension, dict):
            name = dvt_extension.get("name")
            if isinstance(name, str) and name.strip():
                identities.add(name)
                aliases.add(name)
            display_name = dvt_extension.get("display_name")
            if isinstance(display_name, str) and display_name.strip():
                aliases.add(display_name)

    def normalize(values: set[str]) -> set[str]:
        return {
            normalized
            for value in values
            if (normalized := _normalize_extension_test_identity(value))
        }

    return normalize(identities), normalize(aliases)


def _resolve_extensions_root(
    *,
    project_dir: Path,
    extensions_data_dir: str | None,
) -> Path:
    if extensions_data_dir is None:
        return Path(os.getenv("EXTENSIONS_VOLUME_PATH", project_dir / "extensions")).resolve()
    path = Path(extensions_data_dir)
    return path.resolve() if path.is_absolute() else (project_dir / path).resolve()


def collect_extension_test_dirs(
    *,
    project_dir: Path,
    tests_type: str,
    extensions_data_dir: str | None = None,
) -> list[str]:
    """Collect extension test paths and fail fast when the same extension is present twice."""
    extensions_root = _resolve_extensions_root(
        project_dir=project_dir,
        extensions_data_dir=extensions_data_dir,
    )
    if not extensions_root.is_dir():
        return []

    result: list[str] = []
    identities: dict[str, Path] = {}
    for entry in sorted(extensions_root.iterdir()):
        if not entry.is_dir():
            continue
        candidate = entry / "tests" / tests_type
        if not candidate.is_dir():
            continue
        entry_identities, _ = _extension_test_names(entry)
        for identity in entry_identities:
            previous = identities.get(identity)
            if previous is not None and previous != entry:
                raise ValueError(
                    "Duplicate extension test identity "
                    f"'{identity}' found in '{previous}' and '{entry}'. "
                    "Use an isolated extensions directory or remove the legacy duplicate."
                )
            identities[identity] = entry
        result.append(f"extensions/{entry.name}/tests/{tests_type}")
    return result


def resolve_extension_test_target(
    *,
    project_dir: Path,
    extension_name: str,
    tests_type: str,
    extensions_data_dir: str | None = None,
) -> str:
    """Resolve tests for one extension by directory, package, manifest, or display name."""
    extensions_root = _resolve_extensions_root(
        project_dir=project_dir,
        extensions_data_dir=extensions_data_dir,
    )
    if not extensions_root.is_dir():
        raise ValueError(f"Extensions directory not found: {extensions_root}")

    requested_identity = _normalize_extension_test_identity(extension_name)
    matches: list[Path] = []
    for entry in sorted(extensions_root.iterdir()):
        if not entry.is_dir():
            continue
        _, aliases = _extension_test_names(entry)
        if requested_identity in aliases:
            matches.append(entry)

    if len(matches) > 1:
        paths = ", ".join(str(entry) for entry in matches)
        raise ValueError(
            f"Extension name '{extension_name}' is ambiguous across test trees: {paths}"
        )
    if matches:
        entry = matches[0]
        candidate = entry / "tests" / tests_type
        if not candidate.is_dir():
            raise ValueError(
                f"Extension '{entry.name}' has no tests/{tests_type} directory"
            )
        return f"extensions/{entry.name}/tests/{tests_type}"

    available = [
        e.name
        for e in sorted(extensions_root.iterdir())
        if e.is_dir() and (e / "tests" / tests_type).is_dir()
    ]
    hint = f" Available: {', '.join(available)}" if available else ""
    raise ValueError(f"Extension '{extension_name}' not found.{hint}")


def resolve_test_target(
    *,
    project_dir: Path,
    tests_dir: str,
    test_path: str | None,
) -> str:
    normalized_tests_dir = tests_dir.replace("\\", "/")
    project_root = project_dir.resolve()
    tests_root = (project_root / normalized_tests_dir).resolve()
    if not tests_root.exists():
        raise ValueError(f"Tests directory not found: {normalized_tests_dir}")

    if test_path is None:
        return normalized_tests_dir

    raw_target = test_path.strip()
    if not raw_target:
        raise ValueError("Test path must not be empty.")

    path_part, separator, node_selector = raw_target.partition("::")
    if not path_part:
        raise ValueError("Test path must include a file or directory before '::'.")

    candidate = Path(path_part)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    resolved_candidate = candidate.resolve()

    if not resolved_candidate.exists():
        raise ValueError(f"Test path not found: {path_part}")

    try:
        resolved_candidate.relative_to(tests_root)
    except ValueError as exc:
        raise ValueError(
            f"Test path must be inside '{normalized_tests_dir}': {path_part}"
        ) from exc

    relative_target = resolved_candidate.relative_to(project_root).as_posix()
    if not separator:
        return relative_target
    if not node_selector:
        raise ValueError("Pytest node selector after '::' must not be empty.")
    return f"{relative_target}::{node_selector}"


def build_testing_compose_command(project_dir: Path, *arguments: str) -> list[str]:
    command = ["docker", "compose", "--project-directory", str(project_dir)]
    for compose_file in _TEST_COMPOSE_FILES:
        command.extend(["-f", compose_file])
    command.extend(["--profile", "testing", *arguments])
    return command


def build_app_compose_command(project_dir: Path, *arguments: str) -> list[str]:
    command = ["docker", "compose", "--project-directory", str(project_dir)]
    for compose_file in _APP_COMPOSE_FILES:
        command.extend(["-f", compose_file])
    command.extend(arguments)
    return command


def build_prod_compose_command(project_dir: Path, *arguments: str) -> list[str]:
    command = ["docker", "compose", "--project-directory", str(project_dir)]
    for compose_file in _PROD_COMPOSE_FILES:
        command.extend(["-f", compose_file])
    command.extend(arguments)
    return command
