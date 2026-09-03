from __future__ import annotations

import argparse
import ast
import os
import sys
from dataclasses import dataclass
from pathlib import Path

HOST_MODULE_ROOTS = frozenset({"src", "core", "config"})
SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
        ".venv",
        ".venv3.13",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".tox",
        "node_modules",
        "dist",
        "build",
        ".next",
        ".turbo",
    }
)


@dataclass(frozen=True, slots=True)
class ExportBinding:
    target_module: str
    target_name: str | None = None


@dataclass(frozen=True, slots=True)
class ModuleInfo:
    path: Path
    is_package: bool
    exports: dict[str, ExportBinding | None]
    dynamic_exports: frozenset[str]


@dataclass(frozen=True, slots=True)
class DependencyReference:
    repository: str
    file: Path
    line: int
    module: str
    name: str | None = None

    @property
    def qualified_name(self) -> str:
        if self.name is None:
            return self.module
        return f"{self.module}.{self.name}"


@dataclass(frozen=True, slots=True)
class MissingDependency:
    reference: DependencyReference
    reason: str


@dataclass(frozen=True, slots=True)
class ScanError:
    file: Path
    message: str


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    scanned_files: int
    repositories: frozenset[str]
    references: tuple[DependencyReference, ...]
    missing: tuple[MissingDependency, ...]
    scan_errors: tuple[ScanError, ...]


class HostRepositoryIndex:
    """Static index of importable entities owned by the main DVT repository."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self._module_paths: dict[str, tuple[Path, bool] | None] = {}
        self._module_infos: dict[str, ModuleInfo] = {}
        self._module_errors: dict[str, str] = {}

    def module_exists(self, module: str) -> bool:
        return self._get_module_path(module) is not None

    def has_explicit_export(self, module: str, name: str) -> bool:
        if not self.module_exists(module):
            return False
        return self._has_export(module, name, seen=set())

    def resolve(  # noqa: PLR0911 - ordered resolution branches keep diagnostics explicit
        self,
        module: str,
        name: str | None = None,
    ) -> tuple[bool, str | None]:
        if name is None:
            if self.module_exists(module):
                return True, None
            return False, f"module '{module}' was not found in the main repository"

        if not self.module_exists(module):
            return False, f"module '{module}' was not found in the main repository"

        if module != "config" and self.module_exists(f"{module}.{name}"):
            return True, None

        if self._has_export(module, name, seen=set()):
            return True, None

        module_error = self._module_errors.get(module)
        if module_error is not None:
            return False, module_error

        return False, f"entity '{name}' was not found in module '{module}'"

    def dependency_for_attribute_chain(
        self,
        base_module: str,
        attributes: list[str],
    ) -> tuple[str, str | None] | None:
        """Resolve a module-rooted attribute chain to the first non-module entity.

        For example, ``src.enums.ExecMode.METADATA_ONLY`` becomes
        ``("src.enums", "ExecMode")``. Class/enum attributes after that are intentionally
        outside this check: the script validates host modules and imported host entities,
        not arbitrary attributes on those entities.
        """
        current_module = base_module
        for attribute in attributes:
            candidate_module = f"{current_module}.{attribute}"
            if current_module != "config" and self.module_exists(candidate_module):
                current_module = candidate_module
                continue
            return current_module, attribute
        return current_module, None

    def _get_module_path(self, module: str) -> tuple[Path, bool] | None:
        cached = self._module_paths.get(module)
        if module in self._module_paths:
            return cached

        parts = module.split(".")
        if not parts or parts[0] not in HOST_MODULE_ROOTS:
            self._module_paths[module] = None
            return None

        if parts[0] == "config":
            result = (self.repo_root / "config.py", False) if parts == ["config"] else None
            if result is not None and not result[0].is_file():
                result = None
            self._module_paths[module] = result
            return result

        base = self.repo_root.joinpath(*parts)
        module_file = base.with_suffix(".py")
        package_init = base / "__init__.py"

        if module_file.is_file():
            result = (module_file, False)
        elif package_init.is_file():
            result = (package_init, True)
        elif base.is_dir():
            # Namespace packages are importable even without __init__.py.
            result = (base, True)
        else:
            result = None

        self._module_paths[module] = result
        return result

    def _has_export(  # noqa: PLR0911 - recursive export resolution has intentional early exits
        self,
        module: str,
        name: str,
        seen: set[tuple[str, str]],
    ) -> bool:
        key = (module, name)
        if key in seen:
            return False
        seen.add(key)

        info = self._get_module_info(module)
        if info is None:
            return False
        if name in info.dynamic_exports:
            return True
        if name not in info.exports:
            return False

        binding = info.exports[name]
        if binding is None:
            return True

        target_module = binding.target_module
        target_name = binding.target_name
        if not _is_host_module(target_module):
            return True
        if target_name is None:
            return self.module_exists(target_module)
        if target_module != "config" and self.module_exists(f"{target_module}.{target_name}"):
            return True
        return self._has_export(target_module, target_name, seen)

    def _get_module_info(self, module: str) -> ModuleInfo | None:
        if module in self._module_infos:
            return self._module_infos[module]
        module_path = self._get_module_path(module)
        if module_path is None:
            return None

        path, is_package = module_path
        if path.is_dir():
            info = ModuleInfo(
                path=path,
                is_package=True,
                exports={},
                dynamic_exports=frozenset(),
            )
            self._module_infos[module] = info
            return info

        try:
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            self._module_errors[module] = f"failed to analyze module '{module}': {exc}"
            return None

        exports: dict[str, ExportBinding | None] = {}
        dynamic_exports: set[str] = set()
        self._collect_runtime_exports(
            statements=tree.body,
            module=module,
            is_package=is_package,
            exports=exports,
            dynamic_exports=dynamic_exports,
        )
        info = ModuleInfo(
            path=path,
            is_package=is_package,
            exports=exports,
            dynamic_exports=frozenset(dynamic_exports),
        )
        self._module_infos[module] = info
        return info

    def _collect_runtime_exports(
        self,
        *,
        statements: list[ast.stmt],
        module: str,
        is_package: bool,
        exports: dict[str, ExportBinding | None],
        dynamic_exports: set[str],
    ) -> None:
        for statement in statements:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                exports[statement.name] = None
                if (
                    isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and statement.name == "__getattr__"
                ):
                    dynamic_exports.update(_getattr_literal_names(statement))
                continue

            if isinstance(statement, ast.Import):
                for alias in statement.names:
                    local_name = alias.asname or alias.name.split(".")[0]
                    target_module = alias.name if alias.asname else alias.name.split(".")[0]
                    exports[local_name] = ExportBinding(target_module=target_module)
                continue

            if isinstance(statement, ast.ImportFrom):
                source_module = _resolve_import_from_module(
                    current_module=module,
                    current_is_package=is_package,
                    imported_module=statement.module,
                    level=statement.level,
                )
                for alias in statement.names:
                    if alias.name == "*":
                        continue
                    local_name = alias.asname or alias.name
                    if source_module is None:
                        exports[local_name] = None
                    else:
                        exports[local_name] = ExportBinding(
                            target_module=source_module,
                            target_name=alias.name,
                        )
                continue

            if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                for assigned_name in _assigned_names(statement):
                    exports[assigned_name] = None
                continue

            if isinstance(statement, ast.If):
                type_checking = _type_checking_branch(statement.test)
                if type_checking is True:
                    self._collect_runtime_exports(
                        statements=statement.orelse,
                        module=module,
                        is_package=is_package,
                        exports=exports,
                        dynamic_exports=dynamic_exports,
                    )
                elif type_checking is False:
                    self._collect_runtime_exports(
                        statements=statement.body,
                        module=module,
                        is_package=is_package,
                        exports=exports,
                        dynamic_exports=dynamic_exports,
                    )
                else:
                    self._collect_runtime_exports(
                        statements=statement.body + statement.orelse,
                        module=module,
                        is_package=is_package,
                        exports=exports,
                        dynamic_exports=dynamic_exports,
                    )
                continue

            nested_blocks = _runtime_statement_blocks(statement)
            for block in nested_blocks:
                self._collect_runtime_exports(
                    statements=block,
                    module=module,
                    is_package=is_package,
                    exports=exports,
                    dynamic_exports=dynamic_exports,
                )


def analyze_extensions(repo_root: Path, extensions_dir: Path) -> AnalysisResult:
    repo_root = repo_root.resolve()
    extensions_dir = extensions_dir.resolve()
    index = HostRepositoryIndex(repo_root)

    references: list[DependencyReference] = []
    scan_errors: list[ScanError] = []
    repositories: set[str] = set()
    scanned_files = 0

    for file in _iter_python_files(extensions_dir):
        scanned_files += 1
        relative_file = file.relative_to(extensions_dir)
        repository = relative_file.parts[0] if len(relative_file.parts) > 1 else "<root>"
        repositories.add(repository)

        try:
            source = file.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(file))
        except (OSError, UnicodeError, SyntaxError) as exc:
            scan_errors.append(ScanError(file=file, message=str(exc)))
            continue

        references.extend(
            _collect_file_references(
                tree=tree,
                file=file,
                repository=repository,
                index=index,
            )
        )

    unique_references = tuple(
        sorted(
            set(references),
            key=lambda item: (
                item.qualified_name,
                item.repository,
                item.file.as_posix(),
                item.line,
            ),
        )
    )

    missing: list[MissingDependency] = []
    for reference in unique_references:
        exists, reason = index.resolve(reference.module, reference.name)
        if not exists:
            missing.append(
                MissingDependency(
                    reference=reference,
                    reason=reason or "unknown resolution error",
                )
            )

    return AnalysisResult(
        scanned_files=scanned_files,
        repositories=frozenset(repositories),
        references=unique_references,
        missing=tuple(missing),
        scan_errors=tuple(scan_errors),
    )


def _collect_file_references(
    *,
    tree: ast.Module,
    file: Path,
    repository: str,
    index: HostRepositoryIndex,
) -> list[DependencyReference]:
    references: list[DependencyReference] = []
    module_aliases: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _is_host_module(alias.name):
                    continue
                references.append(
                    DependencyReference(
                        repository=repository,
                        file=file,
                        line=node.lineno,
                        module=alias.name,
                    )
                )
                if alias.asname:
                    module_aliases[alias.asname] = alias.name
                else:
                    root_name = alias.name.split(".")[0]
                    module_aliases[root_name] = root_name

        elif isinstance(node, ast.ImportFrom):
            if node.level != 0 or node.module is None or not _is_host_module(node.module):
                continue
            for alias in node.names:
                if alias.name == "*":
                    references.append(
                        DependencyReference(
                            repository=repository,
                            file=file,
                            line=node.lineno,
                            module=node.module,
                        )
                    )
                    continue

                references.append(
                    DependencyReference(
                        repository=repository,
                        file=file,
                        line=node.lineno,
                        module=node.module,
                        name=alias.name,
                    )
                )

                candidate_module = f"{node.module}.{alias.name}"
                if (
                    node.module != "config"
                    and index.module_exists(candidate_module)
                    and not index.has_explicit_export(node.module, alias.name)
                ):
                    module_aliases[alias.asname or alias.name] = candidate_module

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        chain = _attribute_chain(node)
        if chain is None:
            continue
        root_name, attributes = chain
        base_module = module_aliases.get(root_name)
        if base_module is None or not attributes:
            continue
        dependency = index.dependency_for_attribute_chain(base_module, attributes)
        if dependency is None:
            continue
        module, name = dependency
        references.append(
            DependencyReference(
                repository=repository,
                file=file,
                line=node.lineno,
                module=module,
                name=name,
            )
        )

    return references


def _iter_python_files(root: Path):
    for current_dir, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if dirname not in SKIP_DIRS and not (Path(current_dir) / dirname).is_symlink()
        ]
        current_path = Path(current_dir)
        for filename in filenames:
            if filename.endswith((".py", ".pyi")):
                yield current_path / filename


def _is_host_module(module: str) -> bool:
    root = module.split(".", 1)[0]
    return root in HOST_MODULE_ROOTS


def _resolve_import_from_module(
    *,
    current_module: str,
    current_is_package: bool,
    imported_module: str | None,
    level: int,
) -> str | None:
    if level == 0:
        return imported_module

    current_parts = current_module.split(".")
    package_parts = current_parts if current_is_package else current_parts[:-1]
    trim_count = level - 1
    if trim_count > len(package_parts):
        return None
    if trim_count:
        package_parts = package_parts[:-trim_count]
    if imported_module:
        package_parts = [*package_parts, *imported_module.split(".")]
    return ".".join(package_parts) or None


def _assigned_names(statement: ast.Assign | ast.AnnAssign | ast.AugAssign) -> set[str]:
    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]

    result: set[str] = set()
    for target in targets:
        result.update(_target_names(target))
    return result


def _target_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        result: set[str] = set()
        for item in target.elts:
            result.update(_target_names(item))
        return result
    return set()


def _runtime_statement_blocks(statement: ast.stmt) -> list[list[ast.stmt]]:
    if isinstance(statement, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)):
        return [statement.body, statement.orelse] if hasattr(statement, "orelse") else [statement.body]
    if isinstance(statement, (ast.Try, ast.TryStar)):
        return [
            statement.body,
            *[handler.body for handler in statement.handlers],
            statement.orelse,
            statement.finalbody,
        ]
    if isinstance(statement, ast.Match):
        return [case.body for case in statement.cases]
    return []


def _type_checking_branch(test: ast.expr) -> bool | None:
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    if (
        isinstance(test, ast.Attribute)
        and isinstance(test.value, ast.Name)
        and test.value.id == "typing"
        and test.attr == "TYPE_CHECKING"
    ):
        return True
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = _type_checking_branch(test.operand)
        return None if inner is None else not inner
    return None


def _getattr_literal_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    if not function.args.args:
        return set()
    argument_name = function.args.args[0].arg
    names: set[str] = set()

    for node in ast.walk(function):
        if not isinstance(node, ast.Compare):
            continue
        expressions = [node.left, *node.comparators]
        if not any(isinstance(expr, ast.Name) and expr.id == argument_name for expr in expressions):
            continue
        for expression in expressions:
            if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
                names.add(expression.value)
            elif isinstance(expression, (ast.Set, ast.Tuple, ast.List)):
                for item in expression.elts:
                    if isinstance(item, ast.Constant) and isinstance(item.value, str):
                        names.add(item.value)
    return names


def _attribute_chain(node: ast.Attribute) -> tuple[str, list[str]] | None:
    attributes: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        attributes.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    attributes.reverse()
    return current.id, attributes


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _print_result(result: AnalysisResult, *, repo_root: Path, extensions_dir: Path) -> int:
    print(f"DVT repository: {repo_root}")
    print(f"Extensions directory: {extensions_dir}")
    print(
        f"Scanned {result.scanned_files} Python files in "
        f"{len(result.repositories)} extension repositories."
    )

    if result.scan_errors:
        print("\nERROR: failed to parse/read extension files:", file=sys.stderr)
        for error in result.scan_errors:
            path = _display_path(error.file, repo_root)
            print(f"  - {path}: {error.message}", file=sys.stderr)

    if result.missing:
        grouped: dict[str, list[MissingDependency]] = {}
        for missing in result.missing:
            grouped.setdefault(missing.reference.qualified_name, []).append(missing)

        print(
            f"\nERROR: found {len(grouped)} missing host entities/modules "
            f"({len(result.missing)} references):",
            file=sys.stderr,
        )
        for qualified_name in sorted(grouped):
            occurrences = grouped[qualified_name]
            print(f"\n  {qualified_name}", file=sys.stderr)
            print(f"    {occurrences[0].reason}", file=sys.stderr)
            for occurrence in occurrences:
                reference = occurrence.reference
                path = _display_path(reference.file, repo_root)
                print(
                    f"    - [{reference.repository}] {path}:{reference.line}",
                    file=sys.stderr,
                )

    if result.scan_errors:
        return 2
    if result.missing:
        return 1

    unique_entities = {(ref.module, ref.name) for ref in result.references}
    print(
        f"OK: all {len(unique_entities)} referenced host entities/modules exist "
        "in src, core, or config.py."
    )
    return 0


def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    repo_root = get_repo_root()
    parser = argparse.ArgumentParser(
        description=(
            "Check that Python extensions reference existing DVT entities/modules "
            "from src, core, and config.py."
        )
    )
    parser.add_argument(
        "--extensions-dir",
        type=Path,
        default=repo_root / "extensions",
        help="Directory containing extension repositories (default: <repo_root>/extensions).",
    )
    args = parser.parse_args(argv)

    extensions_dir = args.extensions_dir.expanduser()
    if not extensions_dir.is_absolute():
        extensions_dir = (Path.cwd() / extensions_dir).resolve()
    else:
        extensions_dir = extensions_dir.resolve()

    if not extensions_dir.exists():
        print(
            f"ERROR: extensions directory does not exist: {extensions_dir}",
            file=sys.stderr,
        )
        return 2
    if not extensions_dir.is_dir():
        print(
            f"ERROR: extensions path is not a directory: {extensions_dir}",
            file=sys.stderr,
        )
        return 2

    result = analyze_extensions(repo_root, extensions_dir)
    if result.scanned_files == 0:
        print(
            f"ERROR: no Python files found under extensions directory: {extensions_dir}",
            file=sys.stderr,
        )
        return 2

    return _print_result(
        result,
        repo_root=repo_root,
        extensions_dir=extensions_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
