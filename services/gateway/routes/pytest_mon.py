import ast
import hashlib
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field


class PytestEntityLocation(BaseModel):
    absolute_path: str
    relative_path: str
    lineno: int
    end_lineno: int


class PytestEntitySchema(BaseModel):
    name: str
    python_name: str
    qualified_name: str
    signature: str
    description: str | None = None
    code: str
    is_async: bool
    location: PytestEntityLocation


class PytestEntityListResponse(BaseModel):
    root_path: str
    fingerprint: str
    count: int
    items: list[PytestEntitySchema] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class _FileState:
    path: Path
    relative_path: str
    size: int
    mtime_ns: int

    @property
    def version(self) -> tuple[int, int]:
        return self.size, self.mtime_ns


@dataclass(frozen=True)
class _ParsedFile:
    version: tuple[int, int]
    fixtures: tuple[PytestEntitySchema, ...]
    tests: tuple[PytestEntitySchema, ...]
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Snapshot:
    fingerprint: str
    fixtures: tuple[PytestEntitySchema, ...]
    tests: tuple[PytestEntitySchema, ...]
    errors: tuple[str, ...]


class _PytestCatalog:
    def __init__(self, tests_root: Path) -> None:
        self._tests_root = tests_root
        self._lock = threading.RLock()
        self._file_cache: dict[str, _ParsedFile] = {}
        self._snapshot: _Snapshot | None = None

    def get_fixtures_response(self) -> PytestEntityListResponse:
        snapshot = self._get_snapshot()
        return PytestEntityListResponse(
            root_path=str(self._tests_root),
            fingerprint=snapshot.fingerprint,
            count=len(snapshot.fixtures),
            items=list(snapshot.fixtures),
            errors=list(snapshot.errors),
        )

    def get_tests_response(self) -> PytestEntityListResponse:
        snapshot = self._get_snapshot()
        return PytestEntityListResponse(
            root_path=str(self._tests_root),
            fingerprint=snapshot.fingerprint,
            count=len(snapshot.tests),
            items=list(snapshot.tests),
            errors=list(snapshot.errors),
        )

    def _get_snapshot(self) -> _Snapshot:
        with self._lock:
            states = self._collect_file_states()
            fingerprint = self._build_fingerprint(states)

            if self._snapshot and self._snapshot.fingerprint == fingerprint:
                return self._snapshot

            fixtures: list[PytestEntitySchema] = []
            tests: list[PytestEntitySchema] = []
            errors: list[str] = []

            active_paths = {state.relative_path for state in states}

            for state in states:
                cached = self._file_cache.get(state.relative_path)
                if cached is None or cached.version != state.version:
                    cached = self._parse_file(state)
                    self._file_cache[state.relative_path] = cached

                fixtures.extend(cached.fixtures)
                tests.extend(cached.tests)
                errors.extend(cached.errors)

            stale_paths = set(self._file_cache) - active_paths
            for stale_path in stale_paths:
                self._file_cache.pop(stale_path, None)

            fixtures.sort(key=self._sort_key)
            tests.sort(key=self._sort_key)

            snapshot = _Snapshot(
                fingerprint=fingerprint,
                fixtures=tuple(fixtures),
                tests=tuple(tests),
                errors=tuple(sorted(set(errors))),
            )
            self._snapshot = snapshot
            return snapshot

    def _collect_file_states(self) -> list[_FileState]:
        states: list[_FileState] = []
        for path in sorted(self._tests_root.rglob("*.py")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue

            stat_result = path.stat()
            states.append(
                _FileState(
                    path=path,
                    relative_path=path.relative_to(self._tests_root).as_posix(),
                    size=stat_result.st_size,
                    mtime_ns=stat_result.st_mtime_ns,
                )
            )
        return states

    @staticmethod
    def _build_fingerprint(states: Iterable[_FileState]) -> str:
        digest = hashlib.sha256()
        for state in states:
            digest.update(state.relative_path.encode("utf-8"))
            digest.update(str(state.size).encode("ascii"))
            digest.update(str(state.mtime_ns).encode("ascii"))
        return digest.hexdigest()

    @staticmethod
    def _sort_key(entity: PytestEntitySchema) -> tuple[str, int, str]:
        return (
            entity.location.relative_path,
            entity.location.lineno,
            entity.qualified_name,
        )

    def _parse_file(self, state: _FileState) -> _ParsedFile:
        try:
            source = state.path.read_text(encoding="utf-8")
            module = ast.parse(source, filename=str(state.path))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            return _ParsedFile(
                version=state.version,
                fixtures=(),
                tests=(),
                errors=(f"{state.relative_path}: {exc}",),
            )

        source_lines = source.splitlines(keepends=True)
        fixtures: list[PytestEntitySchema] = []
        tests: list[PytestEntitySchema] = []

        self._collect_nodes(
            body=module.body,
            source_lines=source_lines,
            state=state,
            fixtures=fixtures,
            tests=tests,
            class_stack=(),
        )

        return _ParsedFile(
            version=state.version,
            fixtures=tuple(fixtures),
            tests=tuple(tests),
        )

    def _collect_nodes(
        self,
        *,
        body: list[ast.stmt],
        source_lines: list[str],
        state: _FileState,
        fixtures: list[PytestEntitySchema],
        tests: list[PytestEntitySchema],
        class_stack: tuple[ast.ClassDef, ...],
    ) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                self._collect_nodes(
                    body=node.body,
                    source_lines=source_lines,
                    state=state,
                    fixtures=fixtures,
                    tests=tests,
                    class_stack=(*class_stack, node),
                )
                continue

            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            fixture_name = _get_fixture_name(node)
            if fixture_name is not None:
                fixtures.append(
                    _build_entity(
                        node=node,
                        name=fixture_name,
                        source_lines=source_lines,
                        state=state,
                        class_stack=class_stack,
                    )
                )

            if _is_test_node(node, class_stack):
                tests.append(
                    _build_entity(
                        node=node,
                        name=node.name,
                        source_lines=source_lines,
                        state=state,
                        class_stack=class_stack,
                    )
                )


class PytestMonitorRouter(APIRouter):
    def __init__(
        self,
        tests_root: str | Path,
        *,
        prefix: str = "/pytest-mon",
        tags: list[str] | None = None,
        **kwargs,
    ) -> None:
        root_path = Path(tests_root).expanduser().resolve()
        if not root_path.exists():
            raise ValueError(f"Tests path does not exist: {root_path}")
        if not root_path.is_dir():
            raise ValueError(f"Tests path is not a directory: {root_path}")

        super().__init__(prefix=prefix, tags=tags or ["Pytest Monitor"], **kwargs)
        self._catalog = _PytestCatalog(root_path)

        self.add_api_route(
            "/fixtures",
            self.get_fixtures,
            methods=["GET"],
            response_model=PytestEntityListResponse,
            summary="Get pytest fixtures",
        )
        self.add_api_route(
            "/tests",
            self.get_tests,
            methods=["GET"],
            response_model=PytestEntityListResponse,
            summary="Get pytest tests",
        )

    async def get_fixtures(self) -> PytestEntityListResponse:
        return self._catalog.get_fixtures_response()

    async def get_tests(self) -> PytestEntityListResponse:
        return self._catalog.get_tests_response()


def _build_entity(
    *,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    name: str,
    source_lines: list[str],
    state: _FileState,
    class_stack: tuple[ast.ClassDef, ...],
) -> PytestEntitySchema:
    start_line = min([node.lineno, *[decorator.lineno for decorator in node.decorator_list]])
    end_line = node.end_lineno or node.lineno
    code = "".join(source_lines[start_line - 1:end_line]).rstrip()
    qualified_parts = [klass.name for klass in class_stack] + [node.name]

    return PytestEntitySchema(
        name=name,
        python_name=node.name,
        qualified_name=".".join(qualified_parts),
        signature=_build_signature(node, display_name=name),
        description=ast.get_docstring(node, clean=True),
        code=code,
        is_async=isinstance(node, ast.AsyncFunctionDef),
        location=PytestEntityLocation(
            absolute_path=str(state.path),
            relative_path=state.relative_path,
            lineno=start_line,
            end_lineno=end_line,
        ),
    )


def _build_signature(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    display_name: str,
) -> str:
    body: list[ast.stmt] = [ast.Pass()]
    if isinstance(node, ast.AsyncFunctionDef):
        signature_node: ast.AST = ast.AsyncFunctionDef(
            name=display_name,
            args=node.args,
            body=body,
            decorator_list=[],
            returns=node.returns,
            type_comment=node.type_comment,
        )
    else:
        signature_node = ast.FunctionDef(
            name=display_name,
            args=node.args,
            body=body,
            decorator_list=[],
            returns=node.returns,
            type_comment=node.type_comment,
        )

    header = ast.unparse(ast.fix_missing_locations(signature_node)).splitlines()[0]
    return header.removesuffix(":")


def _is_test_node(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    class_stack: tuple[ast.ClassDef, ...],
) -> bool:
    if not node.name.startswith("test_"):
        return False

    if not class_stack:
        return True

    return _is_test_class(class_stack[-1])


def _is_test_class(node: ast.ClassDef) -> bool:
    if node.name.startswith("Test"):
        return True

    for base in node.bases:
        dotted_name = _get_dotted_name(base)
        if dotted_name and dotted_name.split(".")[-1] == "TestCase":
            return True

    return False


def _get_fixture_name(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        dotted_name = _get_dotted_name(target)
        if dotted_name is None or dotted_name.split(".")[-1] != "fixture":
            continue

        if isinstance(decorator, ast.Call):
            for keyword in decorator.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                    return keyword.value.value
        return node.name

    return None


def _get_dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _get_dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None
