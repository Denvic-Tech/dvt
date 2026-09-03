from __future__ import annotations

import ast
import sys
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

ALLOWED_CONFIG_MODULE = "config"
ALLOWED_CONTRACTS_MODULE = "contracts"

# Top-level names that may exist locally but should be treated as third-party modules.
EXTERNAL_OVERRIDE_TOP_LEVEL = {"docker"}

# Rule set is intentionally data-driven for easy extension.
RULES = {
    "core": {
        # Разрешенные top-level модули для импорта.
        "allowed_top_level": {"core"},
        # Разрешать остальные локальные top-level модули (например, docs/) как исключения.
        "allow_local_else": False,
        # Сообщение об ошибке при нарушении правила.
        "error": "core can only import from core or third-party modules",
    },
    "src": {
        # Разрешенные top-level модули для импорта.
        "allowed_top_level": {"src", "core", ALLOWED_CONTRACTS_MODULE, ALLOWED_CONFIG_MODULE},
        # Разрешать остальные локальные top-level модули (например, docs/) как исключения.
        "allow_local_else": False,
        # Сообщение об ошибке при нарушении правила.
        "error": "src can only import from src, core, contracts, config.py or third-party modules",
    },
    "services": {
        # Разрешенные top-level модули для импорта.
        "allowed_top_level": {"src", "core", ALLOWED_CONTRACTS_MODULE, ALLOWED_CONFIG_MODULE},
        # Разрешать остальные локальные top-level модули (например, docs/) как исключения.
        "allow_local_else": False,
        # Сообщение об ошибке при нарушении общего правила.
        "error": (
            "services can only import from their own service, src, core, contracts, config.py "
            "or third-party modules"
        ),
        # Сообщение об ошибке при попытке импортировать другой сервис.
        "cross_service_error": "services may only import from their own service",
    },
}

# Directories/files at repo root are treated as local modules for boundary checks.
LOCAL_TOP_LEVEL = set()
for entry in REPO_ROOT.iterdir():
    name = entry.name
    if name.startswith("."):
        continue
    if entry.is_dir():
        LOCAL_TOP_LEVEL.add(name)
    elif entry.is_file() and entry.suffix == ".py":
        LOCAL_TOP_LEVEL.add(entry.stem)


def _classify_file(rel_path: Path) -> tuple[str, str | None] | None:
    parts = rel_path.parts
    if not parts:
        return None
    if parts[0] == "core":
        return "core", None
    if parts[0] == "src":
        return "src", None
    if parts[0] == "services" and len(parts) > 1:
        return "services", parts[1]
    return None


def _module_parts_for_file(rel_path: Path) -> list[str]:
    return list(rel_path.with_suffix("").parts)


def _resolve_import_parts(
    *, level: int, module: str | None, file_parts: list[str]
) -> list[str]:
    if level == 0:
        return module.split(".") if module else []
    if level > len(file_parts):
        return []
    base = file_parts[:-level]
    if module:
        base = base + module.split(".")
    return base


def _is_local_top_level(name: str) -> bool:
    return name in LOCAL_TOP_LEVEL


def _is_allowed_by_exception(*, category: str, rel_path: Path, parts: list[str]) -> bool:
    rules = RULES.get(category)
    if not rules:
        return False

    import_name = ".".join(parts)
    rel_path_str = rel_path.as_posix()
    for exception in rules.get("exceptions", []):
        file_path_prefix = exception.get("file_path_prefix")
        if file_path_prefix and not rel_path_str.startswith(file_path_prefix):
            continue

        allowed_import_prefixes = exception.get("allowed_import_prefixes", set())
        if any(
            import_name == prefix or import_name.startswith(f"{prefix}.")
            for prefix in allowed_import_prefixes
        ):
            return True

    return False


def _check_import(
    *,
    category: str,
    service_name: str | None,
    rel_path: Path,
    top_level: str,
    parts: list[str],
) -> str | None:
    if not top_level:
        return None

    if top_level in EXTERNAL_OVERRIDE_TOP_LEVEL:
        return None

    rules = RULES.get(category)
    if not rules:
        return None

    if _is_allowed_by_exception(category=category, rel_path=rel_path, parts=parts):
        return None

    if top_level == "services" and category == "services":
        imported_service = parts[1] if len(parts) > 1 else None
        if imported_service == service_name:
            return None
        return rules["cross_service_error"]

    if top_level in rules["allowed_top_level"]:
        return None

    if _is_local_top_level(top_level) and not rules["allow_local_else"]:
        return rules["error"]

    return None


def _iter_python_files(args: list[str]) -> Iterable[Path]:
    if args:
        for arg in args:
            path = Path(arg)
            if not path.is_absolute():
                path = (Path.cwd() / path).resolve()
            if not path.exists():
                alt = (REPO_ROOT / arg).resolve()
                if alt.exists():
                    path = alt
            if path.suffix == ".py" and path.is_file():
                yield path
        return

    # Fallback: scan repo (avoid heavy dirs).
    skip_dirs = {".git", ".venv3.13", "venv", "node_modules", "tmp", "trash"}
    for path in REPO_ROOT.rglob("*.py"):
        if any(part in skip_dirs for part in path.parts):
            continue
        yield path


def main(argv: list[str]) -> int:
    violations: list[str] = []

    for path in _iter_python_files(argv):
        try:
            rel_path = path.resolve().relative_to(REPO_ROOT)
        except ValueError:
            continue

        classification = _classify_file(rel_path)
        if not classification:
            continue
        category, service_name = classification
        file_parts = _module_parts_for_file(rel_path)

        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue

        try:
            tree = ast.parse(source, filename=str(rel_path))
        except SyntaxError as exc:
            violations.append(f"{rel_path}:{exc.lineno}: syntax error prevents import check")
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    top_level = parts[0]
                    reason = _check_import(
                        category=category,
                        service_name=service_name,
                        rel_path=rel_path,
                        top_level=top_level,
                        parts=parts,
                    )
                    if reason:
                        violations.append(
                            f"{rel_path}:{node.lineno}: {reason} (import '{alias.name}')"
                        )
            elif isinstance(node, ast.ImportFrom):
                parts = _resolve_import_parts(
                    level=node.level,
                    module=node.module,
                    file_parts=file_parts,
                )
                top_level = parts[0] if parts else ""
                reason = _check_import(
                    category=category,
                    service_name=service_name,
                    rel_path=rel_path,
                    top_level=top_level,
                    parts=parts,
                )
                if reason:
                    module_name = "." * node.level + (node.module or "")
                    violations.append(
                        f"{rel_path}:{node.lineno}: {reason} (from '{module_name}')"
                    )

    if violations:
        print("Import boundary violations detected:")
        for item in violations:
            print(f"- {item}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
