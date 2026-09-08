from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from types import ModuleType

from src.extensions.registry import RegisteredExtension
from src.node_dsl.base_node.base import BaseNode

from .manifests import load_node_package_manifest
from .types import NodePackageDescriptor, NodePackageManifest


class NodePackageDiscoveryError(RuntimeError):
    pass


def _validate_node_class(
    module: ModuleType,
    *,
    package_path: Path,
    manifest: NodePackageManifest,
    extension: RegisteredExtension | None = None,
) -> NodePackageDescriptor:
    package_module = module.__name__
    if not hasattr(module, "NODE_CLASS"):
        raise NodePackageDiscoveryError(
            f"Node package '{package_module}' at '{package_path}' does not export NODE_CLASS"
        )
    node_cls = module.NODE_CLASS
    if not inspect.isclass(node_cls):
        raise NodePackageDiscoveryError(
            f"NODE_CLASS in '{package_module}' must be a Python class, got {type(node_cls).__name__}"
        )
    if node_cls is BaseNode or not issubclass(node_cls, BaseNode):
        raise NodePackageDiscoveryError(
            f"NODE_CLASS in '{package_module}' must be a concrete BaseNode subclass"
        )
    if inspect.isabstract(node_cls):
        raise NodePackageDiscoveryError(
            f"NODE_CLASS in '{package_module}' must not be abstract"
        )
    if node_cls.__module__ != package_module and not node_cls.__module__.startswith(
        f"{package_module}."
    ):
        raise NodePackageDiscoveryError(
            f"NODE_CLASS '{node_cls.__name__}' from '{node_cls.__module__}' does not belong to "
            f"node package '{package_module}'"
        )

    if extension is not None:
        node_cls.EXTENSION_NAME = extension.name
        node_cls.EXTENSION_VERSION = extension.version

    return NodePackageDescriptor(
        node_name=node_cls.__name__,
        node_cls=node_cls,
        package_module=package_module,
        package_path=package_path.resolve(),
        manifest=manifest,
        provider="extension" if extension is not None else "builtin",
        extension_name=extension.name if extension is not None else None,
        extension_version=extension.version if extension is not None else None,
        legacy=False,
    )


def load_node_package(
    package_module: str,
    package_path: Path,
    *,
    extension: RegisteredExtension | None = None,
) -> NodePackageDescriptor:
    manifest_path = package_path / "node.yaml"
    manifest = load_node_package_manifest(manifest_path)
    try:
        module = importlib.import_module(package_module)
    except Exception as exc:
        raise NodePackageDiscoveryError(
            f"Failed to import node package '{package_module}' from '{package_path}': {exc}"
        ) from exc
    return _validate_node_class(
        module,
        package_path=package_path,
        manifest=manifest,
        extension=extension,
    )


def discover_builtin_node_packages(
    nodes_root: Path,
    *,
    package_prefix: str = "src.nodes",
) -> list[NodePackageDescriptor]:
    if not nodes_root.is_dir():
        raise NodePackageDiscoveryError(
            f"Built-in node root not found or is not a directory: '{nodes_root}'"
        )

    descriptors: list[NodePackageDescriptor] = []
    for category_dir in sorted(nodes_root.iterdir(), key=lambda item: item.name.casefold()):
        if category_dir.name.startswith("_"):
            continue
        if category_dir.is_file():
            if category_dir.name == "__init__.py":
                continue
            if category_dir.suffix == ".py" and not category_dir.name.startswith("_"):
                raise NodePackageDiscoveryError(
                    f"Public flat module is not allowed under built-in node root: '{category_dir}'"
                )
            continue
        if not category_dir.is_dir():
            continue

        category_init = category_dir / "__init__.py"
        if not category_init.is_file():
            raise NodePackageDiscoveryError(
                f"Built-in node category must be a Python package: missing '{category_init}'"
            )

        for child in sorted(category_dir.iterdir(), key=lambda item: item.name.casefold()):
            if child.name.startswith("_"):
                continue
            if child.is_file():
                if child.name == "__init__.py":
                    continue
                if child.suffix == ".py":
                    raise NodePackageDiscoveryError(
                        f"Public flat node module is not allowed: '{child}'. "
                        "Use a node package with node.yaml."
                    )
                continue
            if not child.is_dir():
                continue

            manifest_path = child / "node.yaml"
            if not manifest_path.is_file():
                raise NodePackageDiscoveryError(
                    f"Public built-in node directory '{child}' is missing node.yaml"
                )
            init_path = child / "__init__.py"
            if not init_path.is_file():
                raise NodePackageDiscoveryError(
                    f"Built-in node package '{child}' is missing __init__.py"
                )

            package_module = f"{package_prefix}.{category_dir.name}.{child.name}"
            descriptors.append(load_node_package(package_module, child))

    return descriptors


def descriptor_from_extension_package_module(
    module: ModuleType,
    *,
    extension: RegisteredExtension,
) -> NodePackageDescriptor | None:
    module_file = getattr(module, "__file__", None)
    if not module_file:
        return None
    package_path = Path(module_file).resolve().parent
    manifest_path = package_path / "node.yaml"
    if not manifest_path.is_file():
        return None
    manifest = load_node_package_manifest(manifest_path)
    return _validate_node_class(
        module,
        package_path=package_path,
        manifest=manifest,
        extension=extension,
    )
