#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Finding:
    severity: str
    path: str
    message: str


@dataclass
class AuditReport:
    findings: list[Finding] = field(default_factory=list)

    def add(self, severity: str, path: Path, message: str) -> None:
        self.findings.append(Finding(severity=severity, path=str(path), message=message))

    def has_errors(self) -> bool:
        return any(item.severity == "ERROR" for item in self.findings)


REQUIRED_DIRS = ("domain", "flow", "infra")
FORBIDDEN_DOMAIN_IMPORT_PREFIXES = (
    "fastapi",
    "pydantic",
    "sqlalchemy",
    "sqlmodel",
    "src.clients",
    "src.crud",
    "src.db",
    "src.dto",
    "src.models",
    "src.schemas",
)
FORBIDDEN_FLOW_IMPORT_PREFIXES = FORBIDDEN_DOMAIN_IMPORT_PREFIXES
FORBIDDEN_CONTRACT_TYPE_NAMES = {
    "AsyncSession",
    "BaseModel",
    "DeclarativeBase",
    "Row",
    "Select",
    "Session",
    "SQLModel",
}
REPOSITORY_METHOD_WARNING_THRESHOLD = 7


def import_targets(file_path: Path) -> list[str]:
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = "." * node.level + module
            targets.append(module)
    return targets


def read_ast(file_path: Path) -> ast.AST:
    source = file_path.read_text(encoding="utf-8")
    return ast.parse(source, filename=str(file_path))


def annotation_names(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()

    names: set[str] = set()

    class Collector(ast.NodeVisitor):
        def visit_Name(self, inner_node: ast.Name) -> None:
            names.add(inner_node.id)

        def visit_Attribute(self, inner_node: ast.Attribute) -> None:
            names.add(inner_node.attr)
            self.generic_visit(inner_node)

    Collector().visit(node)
    return names


def class_base_names(node: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for base in node.bases:
        names.update(annotation_names(base))
    return names


def imports_prefix(target: str, prefixes: tuple[str, ...]) -> bool:
    normalized = target.lstrip(".")
    return any(normalized == prefix or normalized.startswith(f"{prefix}.") for prefix in prefixes)


def check_required_dirs(module_path: Path, report: AuditReport) -> None:
    for name in REQUIRED_DIRS:
        target = module_path / name
        if not target.is_dir():
            report.add("ERROR", target, f"Missing required layer directory: {name}")


def check_disallowed_dirs(module_path: Path, report: AuditReport) -> None:
    legacy = module_path / "flows"
    if legacy.exists():
        report.add("ERROR", legacy, "Use `flow/`, not `flows/`.")

    flow_repositories = module_path / "flow" / "repositories"
    if flow_repositories.exists():
        report.add("ERROR", flow_repositories, "Do not create flow/repositories; keep contracts in domain.")

    flow_gateways = module_path / "flow" / "gateways"
    if flow_gateways.exists():
        report.add("ERROR", flow_gateways, "Do not create flow/gateways; keep contracts in domain.")


def check_use_case_layout(module_path: Path, report: AuditReport) -> None:
    monolith = module_path / "flow" / "use_cases.py"
    if monolith.exists():
        report.add("ERROR", monolith, "Monolithic flow/use_cases.py detected; split use cases by file.")

    use_cases_dir = module_path / "flow" / "use_cases"
    if not use_cases_dir.is_dir():
        report.add("ERROR", use_cases_dir, "Missing flow/use_cases directory.")
        return

    use_case_files = [path for path in use_cases_dir.glob("*.py") if path.name != "__init__.py"]
    if not use_case_files:
        report.add("WARNING", use_cases_dir, "No concrete use case files found.")
        return

    for file_path in use_case_files:
        tree = read_ast(file_path)
        has_use_case_class = False
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            method_names = {
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            if "execute" in method_names:
                has_use_case_class = True
                break
        if not has_use_case_class:
            report.add(
                "ERROR",
                file_path,
                "Each use case file must expose a class with an `execute` method.",
            )


def classify_layer(module_path: Path, file_path: Path) -> str | None:
    try:
        relative = file_path.relative_to(module_path)
    except ValueError:
        return None
    if not relative.parts:
        return None
    return relative.parts[0]


def check_import_boundaries(module_path: Path, report: AuditReport) -> None:
    for file_path in module_path.rglob("*.py"):
        layer = classify_layer(module_path, file_path)
        if layer not in {"domain", "flow", "infra"}:
            continue

        for target in import_targets(file_path):
            if layer == "domain":
                if "flow" in target or "infra" in target:
                    report.add(
                        "ERROR",
                        file_path,
                        f"Domain layer imports forbidden dependency: {target}",
                    )
                if imports_prefix(target, FORBIDDEN_DOMAIN_IMPORT_PREFIXES) or ".db_models" in target:
                    report.add(
                        "ERROR",
                        file_path,
                        f"Domain layer imports transport, framework, or DB detail: {target}",
                    )
            elif layer == "flow":
                if "infra" in target:
                    report.add(
                        "ERROR",
                        file_path,
                        f"Flow layer imports forbidden infra dependency: {target}",
                    )
                if imports_prefix(target, FORBIDDEN_FLOW_IMPORT_PREFIXES):
                    report.add(
                        "ERROR",
                        file_path,
                        f"Flow layer imports transport, framework, or persistence detail: {target}",
                    )


def check_domain_contract_types(module_path: Path, report: AuditReport) -> None:
    domain_root = module_path / "domain"
    for subdir in ("repositories", "gateways"):
        target_dir = domain_root / subdir
        if not target_dir.is_dir():
            continue

        for file_path in target_dir.rglob("*.py"):
            tree = read_ast(file_path)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    forbidden_bases = class_base_names(node) & FORBIDDEN_CONTRACT_TYPE_NAMES
                    if forbidden_bases:
                        report.add(
                            "ERROR",
                            file_path,
                            "Domain contract inherits forbidden framework or transport type: "
                            + ", ".join(sorted(forbidden_bases)),
                        )
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names = set()
                    names.update(annotation_names(node.returns))
                    for arg in (
                        *node.args.posonlyargs,
                        *node.args.args,
                        *node.args.kwonlyargs,
                    ):
                        names.update(annotation_names(arg.annotation))
                    if node.args.vararg:
                        names.update(annotation_names(node.args.vararg.annotation))
                    if node.args.kwarg:
                        names.update(annotation_names(node.args.kwarg.annotation))

                    leaked = names & FORBIDDEN_CONTRACT_TYPE_NAMES
                    if leaked:
                        report.add(
                            "ERROR",
                            file_path,
                            "Domain contract leaks forbidden framework, transport, or persistence "
                            "types in signatures: " + ", ".join(sorted(leaked)),
                        )


def check_no_compat_shims_in_core_layers(module_path: Path, report: AuditReport) -> None:
    for layer in ("domain", "flow"):
        layer_dir = module_path / layer
        if not layer_dir.is_dir():
            continue

        for file_path in layer_dir.rglob("*.py"):
            stem = file_path.stem.lower()
            if "compat" in stem or "shim" in stem:
                report.add(
                    "ERROR",
                    file_path,
                    "Compatibility shim detected inside core DDD-lite layer.",
                )


def check_registered_exception_usage(module_path: Path, report: AuditReport) -> None:
    for file_path in module_path.rglob("*.py"):
        if file_path.name == "exceptions.py":
            continue

        tree = read_ast(file_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "src.exception_registry":
                for alias in node.names:
                    if alias.name == "RegisteredException":
                        report.add(
                            "ERROR",
                            file_path,
                            "Do not import RegisteredException directly outside layer exceptions.py.",
                        )
            if isinstance(node, ast.Raise):
                if isinstance(node.exc, ast.Name) and node.exc.id == "RegisteredException":
                    report.add(
                        "ERROR",
                        file_path,
                        "Do not raise RegisteredException directly; declare a layer-specific exception.",
                    )
                elif (
                    isinstance(node.exc, ast.Call)
                    and isinstance(node.exc.func, ast.Name)
                    and node.exc.func.id == "RegisteredException"
                ):
                    report.add(
                        "ERROR",
                        file_path,
                        "Do not raise RegisteredException directly; declare a layer-specific exception.",
                    )


def check_repository_contract_size(module_path: Path, report: AuditReport) -> None:
    repositories_dir = module_path / "domain" / "repositories"
    if not repositories_dir.is_dir():
        return

    for file_path in repositories_dir.rglob("*.py"):
        tree = read_ast(file_path)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            method_count = sum(
                1 for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
            if method_count > REPOSITORY_METHOD_WARNING_THRESHOLD:
                report.add(
                    "WARNING",
                    file_path,
                    f"Repository contract looks overloaded ({method_count} methods); consider moving "
                    "orchestration-heavy behavior into flow use cases.",
                )


def check_optional_guidance(module_path: Path, report: AuditReport) -> None:
    repositories = module_path / "domain" / "repositories"
    gateways = module_path / "domain" / "gateways"
    if not repositories.is_dir():
        report.add("WARNING", repositories, "Missing domain/repositories directory.")
    if not gateways.is_dir():
        report.add("WARNING", gateways, "Missing domain/gateways directory.")

    providers = module_path / "flow" / "providers.py"
    if not providers.exists():
        report.add("WARNING", providers, "No flow/providers.py present for shared orchestration.")


def audit_module(module_path: Path) -> AuditReport:
    report = AuditReport()
    if not module_path.is_dir():
        report.add("ERROR", module_path, "Module path does not exist.")
        return report

    check_required_dirs(module_path, report)
    check_disallowed_dirs(module_path, report)
    check_use_case_layout(module_path, report)
    check_import_boundaries(module_path, report)
    check_domain_contract_types(module_path, report)
    check_no_compat_shims_in_core_layers(module_path, report)
    check_registered_exception_usage(module_path, report)
    check_repository_contract_size(module_path, report)
    check_optional_guidance(module_path, report)
    return report


def print_report(report: AuditReport) -> None:
    if not report.findings:
        print("OK: no structural findings")
        return

    for item in report.findings:
        print(f"{item.severity}: {item.path}: {item.message}")

    error_count = sum(1 for item in report.findings if item.severity == "ERROR")
    warning_count = sum(1 for item in report.findings if item.severity == "WARNING")
    print(f"Summary: {error_count} error(s), {warning_count} warning(s)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a bounded context module structure.")
    parser.add_argument("module_path")
    args = parser.parse_args()

    report = audit_module(Path(args.module_path).resolve())
    print_report(report)
    return 1 if report.has_errors() else 0


if __name__ == "__main__":
    raise SystemExit(main())
