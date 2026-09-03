from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[5]
_MODULE_ROOT = _REPO_ROOT / "src" / "modules" / "task_execution"

_DOMAIN_FORBIDDEN = (
    "src.modules.task_execution.flow",
    "src.modules.task_execution.infra",
    "src.models",
    "src.schemas",
    "src.dto",
    "src.crud",
    "src.clients",
    "src.db",
    "fastapi",
    "pydantic",
    "sqlmodel",
    "sqlalchemy",
)
_FLOW_FORBIDDEN = (
    "src.modules.task_execution.infra",
    "src.models",
    "src.schemas",
    "src.dto",
    "src.crud",
    "src.clients",
    "src.db",
    "fastapi",
    "pydantic",
    "sqlmodel",
    "sqlalchemy",
)


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(_REPO_ROOT).with_suffix("").parts)


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    current_package = _module_name(path).rsplit(".", 1)[0]
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = importlib.util.resolve_name("." * node.level + module, current_package)
            imports.append(module)
    return imports


def _assert_boundaries(layer: str, forbidden: tuple[str, ...]) -> None:
    violations: list[str] = []
    for path in sorted((_MODULE_ROOT / layer).rglob("*.py")):
        for imported in _imported_modules(path):
            if any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in forbidden):
                violations.append(f"{path.relative_to(_REPO_ROOT)} -> {imported}")
    assert not violations, "DDD boundary violations:\n" + "\n".join(violations)


def test_task_execution_domain_import_boundaries() -> None:
    _assert_boundaries("domain", _DOMAIN_FORBIDDEN)


def test_task_execution_flow_import_boundaries() -> None:
    _assert_boundaries("flow", _FLOW_FORBIDDEN)


def test_repository_and_gateway_contracts_exist_only_in_domain() -> None:
    violations: list[str] = []
    for layer in ("flow", "infra"):
        for path in sorted((_MODULE_ROOT / layer).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "typing":
                    if any(alias.name == "Protocol" for alias in node.names):
                        violations.append(str(path.relative_to(_REPO_ROOT)))
                if isinstance(node, ast.ClassDef):
                    for base in node.bases:
                        if isinstance(base, ast.Name) and base.id == "Protocol":
                            violations.append(str(path.relative_to(_REPO_ROOT)))
    assert not violations, "Contracts outside domain: " + ", ".join(sorted(set(violations)))


def _production_python_files() -> list[Path]:
    return [
        *sorted((_REPO_ROOT / "src").rglob("*.py")),
        *sorted((_REPO_ROOT / "services").rglob("*.py")),
    ]


def test_production_has_no_legacy_task_lifecycle_writes() -> None:
    forbidden_calls = {
        "mark_error",
        "mark_success",
        "mark_canceled",
        "mark_started",
        "mark_running",
        "mark_cancel_requested",
    }
    violations: list[str] = []
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            owner = node.func.value
            if (
                isinstance(owner, ast.Name)
                and owner.id == "task_crud"
                and node.func.attr in forbidden_calls
            ):
                violations.append(
                    f"{path.relative_to(_REPO_ROOT)}:{node.lineno} task_crud.{node.func.attr}"
                )
    assert not violations, "Legacy lifecycle writes remain:\n" + "\n".join(violations)


def test_production_does_not_import_legacy_task_crud_or_model_shim() -> None:
    violations: list[str] = []
    for path in _production_python_files():
        if path in {
            _REPO_ROOT / "src" / "models" / "task.py",
            _REPO_ROOT / "src" / "models" / "__init__.py",
        }:
            continue
        for imported in _imported_modules(path):
            if imported == "src.crud.task" or imported.startswith("src.crud.task."):
                violations.append(f"{path.relative_to(_REPO_ROOT)} -> {imported}")
            if imported == "src.models.task" or imported.startswith("src.models.task."):
                violations.append(f"{path.relative_to(_REPO_ROOT)} -> {imported}")
    assert not violations, "Legacy task imports remain:\n" + "\n".join(violations)


def test_task_record_is_created_only_inside_task_execution() -> None:
    violations: list[str] = []
    for path in _production_python_files():
        if path.is_relative_to(_MODULE_ROOT):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "TaskRecord":
                violations.append(f"{path.relative_to(_REPO_ROOT)}:{node.lineno}")
    assert not violations, "TaskRecord writes/creation outside Task Execution:\n" + "\n".join(violations)


def test_task_lifecycle_enums_are_not_redeclared_in_src_enums() -> None:
    enums_path = _REPO_ROOT / "src" / "enums.py"
    tree = ast.parse(enums_path.read_text(encoding="utf-8"), filename=str(enums_path))
    forbidden = {"TaskStatus", "TaskSource", "TaskControlCommand", "TaskTerminationReason"}
    declared = {node.name for node in tree.body if isinstance(node, ast.ClassDef)} & forbidden
    assert not declared, f"Task lifecycle enums must be owned by task_execution.domain: {sorted(declared)}"
