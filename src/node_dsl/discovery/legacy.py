from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

from src.extensions.registry import RegisteredExtension
from src.node_dsl.base_node.base import BaseNode

from .packages import descriptor_from_extension_package_module
from .types import NodePackageDescriptor


def _is_private_relative_path(path: Path) -> bool:
    return any(part.startswith("_") for part in path.parts)


def import_extension_node_modules(
    directory: Path,
    *,
    module_prefix: str,
) -> dict[str, ModuleType]:
    """Import mixed extension catalogs: package nodes plus legacy flat modules."""
    importlib.invalidate_caches()
    if not directory.is_dir():
        raise ImportError(f"Node directory not found or is not a directory: {directory}")

    imported: dict[str, ModuleType] = {}
    package_roots: set[Path] = set()

    for child in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
        if child.name.startswith("_") or not child.is_dir():
            continue
        manifest_path = child / "node.yaml"
        if not manifest_path.is_file():
            continue
        init_path = child / "__init__.py"
        if not init_path.is_file():
            raise ImportError(f"Extension node package '{child}' is missing __init__.py")

        package_name = f"{module_prefix}.{child.name}"
        sys.modules.pop(package_name, None)
        spec = importlib.util.spec_from_file_location(
            package_name,
            init_path,
            submodule_search_locations=[str(child)],
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create import spec for node package '{child}'")
        module = importlib.util.module_from_spec(spec)
        sys.modules[package_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(package_name, None)
            raise
        imported[package_name] = module
        package_roots.add(child.resolve())

    paths = sorted(directory.rglob("*.py"), key=lambda item: item.as_posix().casefold())
    for path in paths:
        relative_path = path.relative_to(directory)
        if _is_private_relative_path(relative_path):
            continue
        resolved = path.resolve()
        if any(root == resolved.parent or root in resolved.parents for root in package_roots):
            continue

        module_stem = relative_path.with_suffix("").as_posix().replace("/", ".")
        module_name = f"{module_prefix}.{module_stem}"
        sys.modules.pop(module_name, None)
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create import spec for node module '{path}'")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        imported[module_name] = module

    return imported


def discover_extension_node_descriptors(
    imported_modules: Mapping[str, ModuleType],
    *,
    extension: RegisteredExtension,
) -> list[NodePackageDescriptor]:
    found: list[NodePackageDescriptor] = []
    for module_name, module in sorted(imported_modules.items()):
        package_descriptor = descriptor_from_extension_package_module(
            module,
            extension=extension,
        )
        if package_descriptor is not None:
            found.append(package_descriptor)
            continue

        for _, node_cls in inspect.getmembers(module, inspect.isclass):
            if node_cls is BaseNode or node_cls.__module__ != module_name:
                continue
            if not issubclass(node_cls, BaseNode) or inspect.isabstract(node_cls):
                continue
            node_cls.EXTENSION_NAME = extension.name
            node_cls.EXTENSION_VERSION = extension.version
            found.append(
                NodePackageDescriptor(
                    node_name=node_cls.__name__,
                    node_cls=node_cls,
                    package_module=module_name,
                    package_path=Path(module.__file__).resolve().parent if module.__file__ else None,
                    manifest=None,
                    provider="extension",
                    extension_name=extension.name,
                    extension_version=extension.version,
                    legacy=True,
                )
            )
    unique: list[NodePackageDescriptor] = []
    seen_classes: set[type[BaseNode]] = set()
    for descriptor in found:
        if descriptor.node_cls in seen_classes:
            continue
        seen_classes.add(descriptor.node_cls)
        unique.append(descriptor)
    return unique
