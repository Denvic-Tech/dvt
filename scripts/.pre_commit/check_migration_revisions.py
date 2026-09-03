from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
RELEASE_PATH = REPO_ROOT / "RELEASE"
RELEASE_FORMAT_VERSION = "1"
RELEASE_FORMAT_KEY = "RELEASE_FORMAT_VERSION"
ALEMBIC_REVISION_KEY = "ALEMBIC_REVISION"

_RELEASE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_REVISION_PATTERN = re.compile(r"^\d{4}$")
_FORBIDDEN_RELEASE_TOKENS = ("${", "$(", "`")


class MigrationValidationError(ValueError):
    pass


class ReleaseValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RevisionInfo:
    path: Path
    revision: str
    down_revisions: tuple[str, ...]
    dependencies: tuple[str, ...]


@dataclass(frozen=True)
class MigrationGraph:
    revisions: dict[str, RevisionInfo]
    base: str
    head: str


def _get_assignment_value(tree: ast.Module, name: str, path: Path) -> ast.AST:
    values: list[ast.AST] = []

    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue

        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            if value is None:
                raise MigrationValidationError(f"{path}: '{name}' has no value")
            values.append(value)

    if len(values) != 1:
        raise MigrationValidationError(
            f"{path}: expected exactly one top-level '{name}' assignment, found {len(values)}"
        )
    return values[0]


def _parse_revision_references(node: ast.AST, name: str, path: Path) -> tuple[str, ...]:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError) as exc:
        raise MigrationValidationError(
            f"{path}: '{name}' must be a string, a tuple/list of strings, or None"
        ) from exc

    if value is None:
        return ()
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, (tuple, list)):
        values = tuple(value)
    else:
        raise MigrationValidationError(
            f"{path}: '{name}' must be a string, a tuple/list of strings, or None"
        )

    if not values or any(not isinstance(item, str) or not item for item in values):
        raise MigrationValidationError(f"{path}: '{name}' contains an invalid revision ID")
    if len(set(values)) != len(values):
        raise MigrationValidationError(f"{path}: '{name}' contains duplicate revision IDs")
    return values


def read_revision_info(path: Path) -> RevisionInfo:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise MigrationValidationError(f"Could not parse migration {path}: {exc}") from exc

    revision_node = _get_assignment_value(tree, "revision", path)
    try:
        revision = ast.literal_eval(revision_node)
    except (ValueError, TypeError, SyntaxError) as exc:
        raise MigrationValidationError(f"{path}: 'revision' must be a string literal") from exc
    if not isinstance(revision, str) or not revision:
        raise MigrationValidationError(f"{path}: 'revision' must be a non-empty string literal")
    if not _REVISION_PATTERN.fullmatch(revision):
        raise MigrationValidationError(
            f"{path}: 'revision' must contain exactly four digits, got {revision!r}"
        )

    return RevisionInfo(
        path=path,
        revision=revision,
        down_revisions=_parse_revision_references(
            _get_assignment_value(tree, "down_revision", path),
            "down_revision",
            path,
        ),
        dependencies=_parse_revision_references(
            _get_assignment_value(tree, "depends_on", path),
            "depends_on",
            path,
        ),
    )


def get_revision(path: Path) -> str | None:
    try:
        return read_revision_info(path).revision
    except MigrationValidationError:
        return None


def collect_revision_files(versions_dir: Path) -> dict[str, list[Path]]:
    revision_to_paths: dict[str, list[Path]] = defaultdict(list)

    for path in sorted(versions_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        revision = get_revision(path)
        if revision is not None:
            revision_to_paths[revision].append(path)

    return dict(revision_to_paths)


def find_duplicate_revisions(versions_dir: Path) -> dict[str, list[Path]]:
    revision_to_paths = collect_revision_files(versions_dir)
    return {
        revision: paths
        for revision, paths in revision_to_paths.items()
        if len(paths) > 1
    }


def _find_cycle(revisions: dict[str, RevisionInfo]) -> tuple[str, ...] | None:
    visited: set[str] = set()
    active: list[str] = []
    active_set: set[str] = set()

    def visit(revision: str) -> tuple[str, ...] | None:
        if revision in active_set:
            start = active.index(revision)
            return (*active[start:], revision)
        if revision in visited:
            return None

        active.append(revision)
        active_set.add(revision)
        info = revisions[revision]
        for parent in (*info.down_revisions, *info.dependencies):
            cycle = visit(parent)
            if cycle is not None:
                return cycle
        active.pop()
        active_set.remove(revision)
        visited.add(revision)
        return None

    for revision in sorted(revisions):
        cycle = visit(revision)
        if cycle is not None:
            return cycle
    return None


def validate_migration_graph(versions_dir: Path) -> MigrationGraph:
    paths = sorted(path for path in versions_dir.glob("*.py") if path.name != "__init__.py")
    if not paths:
        raise MigrationValidationError(f"No migration files found in {versions_dir}")

    infos = [read_revision_info(path) for path in paths]
    revision_to_paths: dict[str, list[Path]] = defaultdict(list)
    for info in infos:
        revision_to_paths[info.revision].append(info.path)

    duplicates = {
        revision: duplicate_paths
        for revision, duplicate_paths in revision_to_paths.items()
        if len(duplicate_paths) > 1
    }
    if duplicates:
        details = []
        for revision, duplicate_paths in sorted(duplicates.items()):
            files = ", ".join(str(path) for path in sorted(duplicate_paths))
            details.append(f"revision '{revision}': {files}")
        raise MigrationValidationError(
            "Duplicate Alembic revision IDs found after merge/rebase:\n- "
            + "\n- ".join(details)
        )

    revisions = {info.revision: info for info in infos}
    known_revisions = set(revisions)
    for info in infos:
        for relation, referenced in (
            ("down_revision", info.down_revisions),
            ("depends_on", info.dependencies),
        ):
            for target in referenced:
                if target == info.revision:
                    raise MigrationValidationError(
                        f"{info.path}: revision '{info.revision}' references itself in {relation}"
                    )
                if target not in known_revisions:
                    raise MigrationValidationError(
                        f"{info.path}: {relation} references missing revision '{target}'"
                    )

    cycle = _find_cycle(revisions)
    if cycle is not None:
        raise MigrationValidationError(
            "Cycle found in Alembic revision graph: " + " -> ".join(cycle)
        )

    bases = sorted(info.revision for info in infos if not info.down_revisions)
    if len(bases) != 1:
        raise MigrationValidationError(
            f"Expected exactly one Alembic base, found {len(bases)}: {bases}"
        )

    referenced_as_parent = {
        parent
        for info in infos
        for parent in info.down_revisions
    }
    heads = sorted(known_revisions - referenced_as_parent)
    if len(heads) != 1:
        details = [f"{revision}: {revisions[revision].path}" for revision in heads]
        raise MigrationValidationError(
            f"Expected exactly one Alembic head, found {len(heads)}:\n- "
            + "\n- ".join(details)
        )

    return MigrationGraph(revisions=revisions, base=bases[0], head=heads[0])


def parse_release_text(text: str, *, source: str = "RELEASE") -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export ") or "=" not in stripped:
            raise ReleaseValidationError(
                f"{source}:{line_number}: expected an unquoted KEY=VALUE assignment"
            )

        key, value = stripped.split("=", 1)
        if not _RELEASE_KEY_PATTERN.fullmatch(key):
            raise ReleaseValidationError(f"{source}:{line_number}: invalid key '{key}'")
        if key in values:
            raise ReleaseValidationError(f"{source}:{line_number}: duplicate key '{key}'")
        if any(token in value for token in _FORBIDDEN_RELEASE_TOKENS):
            raise ReleaseValidationError(
                f"{source}:{line_number}: shell substitutions are not allowed"
            )
        if "'" in value or '"' in value:
            raise ReleaseValidationError(
                f"{source}:{line_number}: quoted values are not supported"
            )
        values[key] = value

    format_version = values.get(RELEASE_FORMAT_KEY)
    if format_version is not None and format_version != RELEASE_FORMAT_VERSION:
        raise ReleaseValidationError(
            f"{source}: unsupported {RELEASE_FORMAT_KEY}={format_version}"
        )

    revision = values.get(ALEMBIC_REVISION_KEY)
    if revision is not None and not _REVISION_PATTERN.fullmatch(revision):
        raise ReleaseValidationError(
            f"{source}: invalid {ALEMBIC_REVISION_KEY}='{revision}'"
        )
    return values


def sync_release(release_path: Path, expected_revision: str) -> bool:
    if not _REVISION_PATTERN.fullmatch(expected_revision):
        raise ReleaseValidationError(f"Invalid Alembic revision ID '{expected_revision}'")

    if release_path.exists():
        original = release_path.read_text(encoding="utf-8")
        parse_release_text(original, source=str(release_path))
        lines = original.splitlines()
    else:
        original = ""
        lines = []

    replacements = {
        RELEASE_FORMAT_KEY: RELEASE_FORMAT_VERSION,
        ALEMBIC_REVISION_KEY: expected_revision,
    }
    found: set[str] = set()
    updated_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0]
            if key in replacements:
                updated_lines.append(f"{key}={replacements[key]}")
                found.add(key)
                continue
        updated_lines.append(line)

    missing_keys = [key for key in replacements if key not in found]
    if missing_keys and updated_lines and updated_lines[-1] != "":
        updated_lines.append("")
    updated_lines.extend(f"{key}={replacements[key]}" for key in missing_keys)

    updated = "\n".join(updated_lines) + "\n"
    if updated == original:
        return False

    release_path.write_text(updated, encoding="utf-8")
    return True


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the Alembic graph and synchronize RELEASE metadata."
    )
    parser.add_argument(
        "--post-write",
        action="store_true",
        help="Run after Alembic generated a revision and do not fail when RELEASE changes.",
    )
    parser.add_argument(
        "generated_revision",
        nargs="?",
        help="Revision file passed by Alembic's REVISION_SCRIPT_FILENAME token.",
    )
    return parser.parse_args(argv)


def _validate_generated_revision_path(path: str, versions_dir: Path) -> RevisionInfo:
    generated_path = Path(path).resolve()
    versions_path = versions_dir.resolve()

    if not generated_path.is_file():
        raise MigrationValidationError(
            f"Generated migration file does not exist: {generated_path}"
        )
    if generated_path.parent != versions_path:
        raise MigrationValidationError(
            f"Generated migration must be located directly in {versions_path}: {generated_path}"
        )
    return read_revision_info(generated_path)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not VERSIONS_DIR.exists():
        print(f"Directory not found: {VERSIONS_DIR}", file=sys.stderr)
        return 1

    try:
        generated_revision = None
        if args.post_write:
            if args.generated_revision is None:
                raise MigrationValidationError(
                    "--post-write requires the generated revision file path"
                )
            generated_revision = _validate_generated_revision_path(
                args.generated_revision,
                VERSIONS_DIR,
            )
        elif args.generated_revision is not None:
            raise MigrationValidationError(
                "A generated revision file may only be passed together with --post-write"
            )

        graph = validate_migration_graph(VERSIONS_DIR)
        if generated_revision is not None and generated_revision.revision != graph.head:
            raise MigrationValidationError(
                f"Generated revision '{generated_revision.revision}' is not the single "
                f"Alembic head '{graph.head}'"
            )
        changed = sync_release(RELEASE_PATH, graph.head)
    except (MigrationValidationError, ReleaseValidationError, OSError) as exc:
        print(f"Alembic migration validation failed:\n{exc}", file=sys.stderr)
        return 1

    if changed:
        action = "Generated migration synchronized" if args.post_write else "Updated"
        print(
            f"{action} {RELEASE_PATH.relative_to(REPO_ROOT)} with "
            f"{ALEMBIC_REVISION_KEY}={graph.head}. Stage the file.",
            file=sys.stderr,
        )
        return 0 if args.post_write else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
