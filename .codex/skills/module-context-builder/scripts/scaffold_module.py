#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


MODULE_DOCSTRING = '"""Bounded context module."""\n'


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def touch_init(path: Path) -> None:
    write_file(path, "")


def build_files(module_name: str, include_types: bool, include_value_objects: bool,
                include_policies: bool, include_clients: bool) -> dict[Path, str]:
    class_prefix = "".join(part.capitalize() for part in module_name.split("_"))
    files: dict[Path, str] = {
        Path("__init__.py"): MODULE_DOCSTRING,
        Path("domain/__init__.py"): "",
        Path("domain/entities.py"): (
            "from dataclasses import dataclass\n\n\n"
            f"@dataclass\nclass {class_prefix}Entity:\n"
            '    """Replace with a domain entity."""\n\n'
            "    id: str\n"
        ),
        Path("domain/exceptions.py"): (
            "from src.exception_registry import RegisteredException\n\n\n"
            f"class {class_prefix}DomainError(RegisteredException):\n"
            f'    """Use named domain exceptions instead of raising RegisteredException directly."""\n\n'
            f'    category = "{module_name.upper()}_DOMAIN_ERROR"\n'
        ),
        Path("flow/__init__.py"): "",
        Path("flow/exceptions.py"): (
            "from src.exception_registry import RegisteredException\n\n\n"
            f"class {class_prefix}FlowError(RegisteredException):\n"
            f'    """Use named flow exceptions instead of raising RegisteredException directly."""\n\n'
            f'    category = "{module_name.upper()}_FLOW_ERROR"\n'
        ),
        Path("flow/providers.py"): (
            f"class {class_prefix}Provider:\n"
            '    """Place shared orchestration or caching logic here."""\n\n'
            "    pass\n"
        ),
        Path("flow/use_cases/__init__.py"): "",
        Path(f"flow/use_cases/get_{module_name}.py"): (
            f"class Get{class_prefix}UseCase:\n"
            '    """Replace with a concrete use case class. Keep the primary entrypoint in `execute`."""\n\n'
            "    async def execute(self):\n"
            "        raise NotImplementedError\n"
        ),
        Path("domain/repositories/__init__.py"): "",
        Path(f"domain/repositories/{module_name}.py"): (
            "from typing import Protocol\n\n\n"
            f"class {class_prefix}Repository(Protocol):\n"
            '    """Keep this contract focused on persistence and retrieval, not orchestration."""\n\n'
            "    async def get(self, entity_id: str): ...\n"
            "    async def save(self, entity): ...\n"
        ),
        Path("domain/gateways/__init__.py"): "",
        Path(f"domain/gateways/{module_name}.py"): (
            "from typing import Protocol\n\n\n"
            f"class {class_prefix}Gateway(Protocol):\n"
            "    async def fetch(self, entity_id: str): ...\n"
        ),
        Path("infra/__init__.py"): "",
        Path("infra/db_models.py"): (
            "from sqlmodel import Field, SQLModel\n\n\n"
            f"class {class_prefix}DBItem(SQLModel, table=False):\n"
            '    """Convert to a table model when persistence is introduced."""\n\n'
            "    id: str = Field(...)\n"
        ),
        Path("infra/mappers.py"): (
            f"def map_{module_name}_to_domain(payload):\n"
            '    """Translate transport or persistence payloads into domain objects."""\n\n'
            "    return payload\n"
        ),
        Path("infra/repositories/__init__.py"): "",
        Path(f"infra/repositories/{module_name}.py"): (
            f"from src.modules.{module_name}.domain.repositories.{module_name} import "
            f"{class_prefix}Repository\n\n\n"
            f"class SQL{class_prefix}Repository({class_prefix}Repository):\n"
            '    """Implement domain repository contracts here."""\n\n'
            "    pass\n"
        ),
        Path("infra/gateways/__init__.py"): "",
        Path(f"infra/gateways/{module_name}.py"): (
            f"from src.modules.{module_name}.domain.gateways.{module_name} import "
            f"{class_prefix}Gateway\n\n\n"
            f"class HTTP{class_prefix}Gateway({class_prefix}Gateway):\n"
            '    """Implement domain gateway contracts here."""\n\n'
            "    pass\n"
        ),
    }

    if include_types:
        files[Path("domain/types.py")] = (
            "from enum import StrEnum\n\n\n"
            f"class {class_prefix}Type(StrEnum):\n"
            '    DEFAULT = "default"\n'
        )
    if include_value_objects:
        files[Path("domain/value_objects.py")] = (
            "from dataclasses import dataclass\n\n\n"
            "@dataclass(frozen=True)\n"
            f"class {class_prefix}Id:\n"
            "    value: str\n"
        )
    if include_policies:
        files[Path("domain/policies.py")] = (
            f"class {class_prefix}Policy:\n"
            '    """Place reusable business rules here."""\n\n'
            "    pass\n"
        )
    if include_clients:
        files[Path("infra/clients/__init__.py")] = ""
        files[Path(f"infra/clients/{module_name}.py")] = (
            f"class {class_prefix}Client:\n"
            '    """Wrap external transport details here."""\n\n'
            "    pass\n"
        )

    return files


def scaffold_module(root: Path, module_name: str, include_types: bool, include_value_objects: bool,
                    include_policies: bool, include_clients: bool) -> Path:
    module_dir = root / "src" / "modules" / module_name
    if module_dir.exists():
        raise FileExistsError(f"Module already exists: {module_dir}")

    module_dir.mkdir(parents=True, exist_ok=False)

    files = build_files(
        module_name=module_name,
        include_types=include_types,
        include_value_objects=include_value_objects,
        include_policies=include_policies,
        include_clients=include_clients,
    )
    for relative_path, content in files.items():
        target = module_dir / relative_path
        if relative_path.name == "__init__.py":
            touch_init(target)
            if relative_path == Path("__init__.py"):
                write_file(target, content)
        else:
            write_file(target, content)
    return module_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Scaffold a bounded context module in src/modules.")
    parser.add_argument("module_name")
    parser.add_argument("--root", required=True, help="Repository root.")
    parser.add_argument("--with-types", action="store_true")
    parser.add_argument("--with-value-objects", action="store_true")
    parser.add_argument("--with-policies", action="store_true")
    parser.add_argument("--with-clients", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    module_name = args.module_name.strip()
    if not module_name or not module_name.replace("_", "").isalnum() or module_name != module_name.lower():
        raise SystemExit("module_name must be lowercase snake_case")

    module_dir = scaffold_module(
        root=root,
        module_name=module_name,
        include_types=args.with_types,
        include_value_objects=args.with_value_objects,
        include_policies=args.with_policies,
        include_clients=args.with_clients,
    )
    print(f"Created module scaffold at {module_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
