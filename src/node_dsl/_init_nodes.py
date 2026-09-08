from __future__ import annotations

import inspect
import sys
import types
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from src.extensions import get_all_extensions
from src.extensions.registry import RegisteredExtension
from src.logger import logger
from src.node_dsl.base_node.base import BaseNode
from src.node_dsl.discovery import (
    NodePackageDescriptor,
    discover_builtin_node_packages,
    discover_extension_node_descriptors,
    import_extension_node_modules,
)
from src.node_dsl.registry import (
    definitions as definitions_registry,
    hooks as hooks_registry,
    nodes as nodes_registry,
    packages as packages_registry,
)
from src.node_dsl.registry._bootstrap import (
    mark_bootstrapped,
    registry_transaction,
    reset_bootstrap_state,
)

import config


@dataclass
class RegistryRebuildResult:
    registered_node_count: int
    extension_failures: dict[str, str] = field(default_factory=dict)


@dataclass
class _RegistrySnapshot:
    node_classes: dict
    node_definitions: dict
    hooks: dict
    node_packages: dict


def import_nodes(directory: Path, module_prefix: str | None = None) -> dict[str, types.ModuleType]:
    """Compatibility importer for extensions and older tooling."""
    if module_prefix is None:
        descriptors = discover_builtin_node_packages(directory)
        return {
            descriptor.package_module: sys.modules[descriptor.package_module]
            for descriptor in descriptors
        }
    return import_extension_node_modules(directory, module_prefix=module_prefix)


def init_nodes(
    extension_modules: Mapping[str, Mapping[str, types.ModuleType]] | None = None,
    extensions: Mapping[str, RegisteredExtension] | None = None,
    *,
    strict_extension_names: frozenset[str] = frozenset(),
) -> RegistryRebuildResult:
    extension_modules = extension_modules or {}
    extensions = extensions or {}

    with registry_transaction():
        nodes_dir = Path(config.PROJECT.NODES_DIR)
        logger.info("Discovering built-in node packages from: {}", nodes_dir)
        builtin_descriptors = [
            descriptor
            for descriptor in discover_builtin_node_packages(nodes_dir)
            if _is_node_enabled_by_config(descriptor.node_cls)
        ]
        builtin_classes = [descriptor.node_cls for descriptor in builtin_descriptors]

        descriptors_by_extension: dict[str, list[NodePackageDescriptor]] = {}
        extension_failures: dict[str, str] = {}
        for extension_name, modules in sorted(extension_modules.items()):
            extension = extensions.get(extension_name)
            if extension is None:
                extension_failures[extension_name] = (
                    f"Extension '{extension_name}' node discovery failed: runtime metadata is missing"
                )
                continue
            try:
                descriptors = discover_extension_node_descriptors(
                    modules,
                    extension=extension,
                )
                descriptors_by_extension[extension_name] = [
                    descriptor
                    for descriptor in descriptors
                    if _is_node_enabled_by_config(descriptor.node_cls)
                ]
            except Exception as exc:
                extension_failures[extension_name] = (
                    f"Extension '{extension_name}' node discovery failed: {exc}"
                )

        strict_discovery_failures = strict_extension_names.intersection(extension_failures)
        if strict_discovery_failures:
            details = "; ".join(
                extension_failures[name] for name in sorted(strict_discovery_failures)
            )
            raise ValueError(details)

        classes_by_extension = {
            name: [descriptor.node_cls for descriptor in descriptors]
            for name, descriptors in descriptors_by_extension.items()
            if name not in extension_failures
        }
        extension_failures.update(
            _find_node_name_conflicts(builtin_classes, classes_by_extension)
        )
        strict_failures = strict_extension_names.intersection(extension_failures)
        if strict_failures:
            details = "; ".join(
                extension_failures[name] for name in sorted(strict_failures)
            )
            raise ValueError(details)

        original_snapshot = _snapshot_registries()
        try:
            _clear_registries()
            register_node_packages(builtin_descriptors)

            for extension_name, descriptors in sorted(descriptors_by_extension.items()):
                if extension_name in extension_failures:
                    continue
                extension_snapshot = _snapshot_registries()
                try:
                    register_node_packages(descriptors)
                except Exception as exc:
                    _restore_registries(extension_snapshot)
                    message = f"Extension '{extension_name}' node registration failed: {exc}"
                    extension_failures[extension_name] = message
                    if extension_name in strict_extension_names:
                        raise ValueError(message) from exc

            if not nodes_registry.NODE_CLASSES:
                raise RuntimeError("No node classes were found for registration.")

            registered_nodes_count = len(nodes_registry.NODE_CLASSES)
            registered_definitions_count = len(definitions_registry.NODE_DEFINITIONS)
            registered_packages_count = len(packages_registry.NODE_PACKAGES)
            if registered_nodes_count != registered_definitions_count:
                raise RuntimeError(
                    f"Registered nodes count ({registered_nodes_count}) does not match "
                    f"registered definitions count ({registered_definitions_count})"
                )
            if registered_nodes_count != registered_packages_count:
                raise RuntimeError(
                    f"Registered nodes count ({registered_nodes_count}) does not match "
                    f"registered package descriptors count ({registered_packages_count})"
                )
        except Exception:
            _restore_registries(original_snapshot, restore_bootstrap_state=True)
            raise

        mark_bootstrapped()
        logger.info("Registered {} node classes.", registered_nodes_count)
        return RegistryRebuildResult(
            registered_node_count=registered_nodes_count,
            extension_failures=extension_failures,
        )


def rebuild_node_registries(
    extension_modules: Mapping[str, Mapping[str, types.ModuleType]] | None = None,
    extensions: Mapping[str, RegisteredExtension] | None = None,
    *,
    strict_extension_names: frozenset[str] = frozenset(),
) -> RegistryRebuildResult:
    logger.info("Rebuilding node registries.")
    return init_nodes(
        extension_modules=extension_modules,
        extensions=extensions,
        strict_extension_names=strict_extension_names,
    )


def discover_node_classes(
    imported_modules: Mapping[str, types.ModuleType] | None = None,
    *,
    extensions: Mapping[str, RegisteredExtension] | None = None,
) -> list[type[BaseNode]]:
    """Compatibility class-discovery API for imported extension modules."""
    imported_modules = imported_modules or {}
    extensions = extensions or {}
    if len(extensions) == 1:
        extension = next(iter(extensions.values()))
        return [
            descriptor.node_cls
            for descriptor in discover_extension_node_descriptors(
                imported_modules,
                extension=extension,
            )
            if _is_node_enabled_by_config(descriptor.node_cls)
        ]

    found: list[type[BaseNode]] = []
    for module_name, module in sorted(imported_modules.items()):
        for _, node_cls in inspect.getmembers(module, inspect.isclass):
            if node_cls is BaseNode or node_cls.__module__ != module_name:
                continue
            if not issubclass(node_cls, BaseNode) or inspect.isabstract(node_cls):
                continue
            if not _is_node_enabled_by_config(node_cls):
                continue
            _bind_extension_metadata(node_cls, extensions=extensions)
            found.append(node_cls)
    return list(dict.fromkeys(found))


def _is_node_enabled_by_config(node_cls: type[BaseNode]) -> bool:
    if node_cls.CATEGORY in config.NODES.DISABLED_CATEGORIES:
        return False
    if any(tag in config.NODES.DISABLED_TAGS for tag in node_cls.TAGS):
        return False
    if node_cls.__name__ in config.NODES.DISABLED_NODES:
        return False
    if node_cls.DISABLED:
        return False
    return not (node_cls.EXPERIMENTAL and not config.DEBUG.DEBUG)


def _find_node_name_conflicts(
    builtin_classes: list[type[BaseNode]],
    classes_by_extension: Mapping[str, list[type[BaseNode]]],
) -> dict[str, str]:
    owners: dict[str, set[str]] = {}
    builtin_names = {node_cls.__name__ for node_cls in builtin_classes}
    for extension_name, classes in classes_by_extension.items():
        for node_cls in classes:
            owners.setdefault(node_cls.__name__, set()).add(extension_name)

    failures: dict[str, list[str]] = {}
    for node_name, extension_names in owners.items():
        if node_name in builtin_names:
            for extension_name in extension_names:
                failures.setdefault(extension_name, []).append(
                    f"node '{node_name}' conflicts with a builtin node"
                )
        if len(extension_names) > 1:
            for extension_name in extension_names:
                joined = ", ".join(sorted(extension_names - {extension_name}))
                failures.setdefault(extension_name, []).append(
                    f"node '{node_name}' is also declared by: {joined}"
                )

    return {
        name: f"Extension '{name}' node conflicts: {', '.join(messages)}"
        for name, messages in failures.items()
    }


def register_node_packages(descriptors: list[NodePackageDescriptor]) -> None:
    for descriptor in descriptors:
        node_cls = descriptor.node_cls
        node_name = node_cls.__name__
        if node_name != descriptor.node_name:
            raise ValueError(
                f"Node package descriptor name '{descriptor.node_name}' does not match class "
                f"name '{node_name}'"
            )
        if node_name in nodes_registry.NODE_CLASSES:
            raise ValueError(f"Node class '{node_name}' is already registered.")
        nodes_registry.add(node_cls)
        definitions_registry.build(node_cls, python_module=descriptor.package_module)
        hooks_registry.build(node_cls)
        packages_registry.add(descriptor)


def register_node_classes(node_classes: list[type[BaseNode]]) -> None:
    """Legacy compatibility helper; registry bootstrap uses descriptors instead."""
    descriptors = [
        NodePackageDescriptor(
            node_name=node_cls.__name__,
            node_cls=node_cls,
            package_module=node_cls.__module__,
            package_path=None,
            manifest=None,
            provider=(
                "extension" if node_cls.__module__.startswith("dvt_extensions.") else "builtin"
            ),
            extension_name=getattr(node_cls, "EXTENSION_NAME", None),
            extension_version=getattr(node_cls, "EXTENSION_VERSION", None),
            legacy=True,
        )
        for node_cls in node_classes
    ]
    register_node_packages(descriptors)


def _clear_registries() -> None:
    nodes_registry.clear()
    definitions_registry.clear()
    hooks_registry.clear()
    packages_registry.clear()


def _snapshot_registries() -> _RegistrySnapshot:
    return _RegistrySnapshot(
        node_classes=dict(nodes_registry.NODE_CLASSES),
        node_definitions=dict(definitions_registry.NODE_DEFINITIONS),
        hooks=dict(hooks_registry.HOOKS_REGISTRY),
        node_packages=dict(packages_registry.NODE_PACKAGES),
    )


def _restore_registries(
    snapshot: _RegistrySnapshot, *, restore_bootstrap_state: bool = False
) -> None:
    nodes_registry.NODE_CLASSES.clear()
    nodes_registry.NODE_CLASSES.update(snapshot.node_classes)
    definitions_registry.NODE_DEFINITIONS.clear()
    definitions_registry.NODE_DEFINITIONS.update(snapshot.node_definitions)
    hooks_registry.HOOKS_REGISTRY.clear()
    hooks_registry.HOOKS_REGISTRY.update(snapshot.hooks)
    packages_registry.NODE_PACKAGES.clear()
    packages_registry.NODE_PACKAGES.update(snapshot.node_packages)
    if restore_bootstrap_state:
        if snapshot.node_classes:
            mark_bootstrapped()
        else:
            reset_bootstrap_state()


def _bind_extension_metadata(
    node_cls: type[BaseNode],
    *,
    extensions: Mapping[str, RegisteredExtension] | None = None,
) -> None:
    if node_cls.EXTENSION_NAME and node_cls.EXTENSION_VERSION:
        return
    try:
        node_file = Path(inspect.getfile(node_cls)).resolve()
    except (TypeError, OSError):
        return

    for extension in (extensions or {}).values():
        try:
            node_file.relative_to(extension.root_dir.resolve())
        except ValueError:
            continue
        node_cls.EXTENSION_NAME = extension.name
        node_cls.EXTENSION_VERSION = extension.version
        return


def _is_node_class_active(node_cls: type[BaseNode]) -> bool:
    extension_name = getattr(node_cls, "EXTENSION_NAME", None)
    if not extension_name:
        return not node_cls.__module__.startswith("dvt_extensions.")
    extension = get_all_extensions().get(extension_name)
    if extension is None:
        return False
    try:
        Path(inspect.getfile(node_cls)).resolve().relative_to(extension.root_dir.resolve())
    except (TypeError, OSError, ValueError):
        return False
    return True
