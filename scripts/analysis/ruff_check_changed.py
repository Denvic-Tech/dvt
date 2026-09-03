import argparse
import subprocess
import sys
from pathlib import Path

PYTHON_EXTENSIONS = {".py", ".pyi"}


def run_git(args: list[str], cwd: Path) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )

    # -z в git отдаёт пути через NUL-байт, безопаснее для пробелов и спецсимволов.
    return [
        item.decode("utf-8", errors="replace")
        for item in result.stdout.split(b"\0")
        if item
    ]


def get_repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip()).resolve()


def get_changed_python_files(repo_root: Path) -> list[Path]:
    pathspec = ["--", "*.py", "*.pyi"]

    files: set[str] = set()

    # Изменённые tracked-файлы, но не deleted.
    files.update(
        run_git(
            ["diff", "--name-only", "-z", "--diff-filter=ACMRTUXB", *pathspec],
            cwd=repo_root,
        )
    )

    # Staged-файлы, но не deleted.
    files.update(
        run_git(
            ["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRTUXB", *pathspec],
            cwd=repo_root,
        )
    )

    # Untracked-файлы, с учётом .gitignore.
    files.update(
        run_git(
            ["ls-files", "--others", "--exclude-standard", "-z", *pathspec],
            cwd=repo_root,
        )
    )

    result: list[Path] = []

    for file in sorted(files):
        path = repo_root / file

        if path.exists() and path.suffix in PYTHON_EXTENSIONS:
            result.append(path)

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--relative",
        action="store_true",
        help="Передавать Ruff относительные пути вместо абсолютных.",
    )

    args, extra_ruff_args = parser.parse_known_args()

    repo_root = get_repo_root()
    files = get_changed_python_files(repo_root)

    if not files:
        print("No changed Python files.")
        return 0

    if args.relative:
        ruff_files = [str(file.relative_to(repo_root)) for file in files]
    else:
        ruff_files = [str(file) for file in files]

    command = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--output-format=concise",
        *extra_ruff_args,
        "--",
        *ruff_files,
    ]

    return subprocess.run(command, cwd=repo_root, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
