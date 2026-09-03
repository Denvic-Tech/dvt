from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".idea",
    ".vscode",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".turbo",
    "coverage",
}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".pdf", ".zip", ".gz", ".tar", ".rar", ".7z",
    ".exe", ".dll", ".so", ".dylib",
    ".pyc", ".pyd",
    ".woff", ".woff2", ".ttf", ".otf",
    ".mp3", ".mp4", ".mov", ".avi",
}

SKIP_FILE_EXTENSIONS = {
    ".md"
}


def get_repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip()).resolve()


def run_git_grep(
    *,
    root: Path,
    pattern: str,
    ignore_case: bool,
) -> bool | None:
    """
    Возвращает:
    - True  -> TODO найдены
    - False -> TODO не найдены
    - None  -> git grep не сработал, нужен fallback
    """
    cmd = [
        "git",
        "-C",
        str(root),
        "grep",
        "-n",                  # line numbers
        "-I",                  # ignore binary files
        "--recurse-submodules",
    ]

    if ignore_case:
        cmd.append("-i")

    cmd += ["-E", pattern, "--"]

    result = subprocess.run(
        cmd,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    # git grep:
    # 0 -> matches found
    # 1 -> no matches
    # >1 -> error
    if result.returncode == 0:
        print(result.stdout, end="")
        return True

    if result.returncode == 1:
        return False

    print(
        "WARN: git grep --recurse-submodules failed, fallback to filesystem scan.",
        file=sys.stderr,
    )
    print(result.stderr, file=sys.stderr)
    return None


def is_probably_binary(path: Path) -> bool:
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return True

    try:
        with path.open("rb") as f:
            chunk = f.read(4096)
    except OSError:
        return True

    return b"\0" in chunk


def is_skip(path: Path) -> bool:
    return path.suffix.lower() in SKIP_FILE_EXTENSIONS


def scan_filesystem(
    *,
    root: Path,
    pattern: str,
    ignore_case: bool,
) -> bool:
    """
    Fallback/расширенный режим:
    сканирует файловую систему, включая untracked-файлы и сабмодули.
    """
    flags = re.IGNORECASE if ignore_case else 0
    regex = re.compile(pattern, flags)

    found = False

    for current_dir, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        current_path = Path(current_dir)

        for filename in filenames:
            path = current_path / filename

            if is_probably_binary(path):
                continue

            if is_skip(path):
                continue

            rel_path = path.relative_to(root).as_posix()

            try:
                with path.open(
                    "r",
                    encoding="utf-8",
                    errors="replace",
                    newline="",
                ) as f:
                    for line_no, line in enumerate(f, start=1):
                        if regex.search(line):
                            found = True
                            print(f"{rel_path}:{line_no}:{line.rstrip()}")
            except OSError:
                continue

    return found


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find TODO comments in a Git repository, including submodules.",
    )
    parser.add_argument(
        "--pattern",
        default=r"TODO: ",
        help=r"Regex pattern to search. Default: '\bTODO\b'",
    )
    parser.add_argument(
        "-i",
        "--ignore-case",
        action="store_true",
        help="Case-insensitive search.",
    )
    parser.add_argument(
        "--filesystem",
        action="store_true",
        help=(
            "Scan filesystem instead of git grep. "
            "Includes untracked files, but skips common generated/vendor dirs."
        ),
    )
    parser.add_argument(
        "--fail-on-found",
        action="store_true",
        help="Exit with code 2 if TODO entries were found.",
    )

    args = parser.parse_args()

    root = get_repo_root()

    if args.filesystem:
        found = scan_filesystem(
            root=root,
            pattern=args.pattern,
            ignore_case=args.ignore_case,
        )
    else:
        git_result = run_git_grep(
            root=root,
            pattern=args.pattern,
            ignore_case=args.ignore_case,
        )

        if git_result is None:
            found = scan_filesystem(
                root=root,
                pattern=args.pattern,
                ignore_case=args.ignore_case,
            )
        else:
            found = git_result

    if args.fail_on_found and found:
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())