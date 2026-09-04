from pathlib import Path

import pytest

from src.extensions import loader, registry, runtime
from src.extensions.runtime import ExtensionRuntimeLoadError, ExtensionRuntimeSpec
from src.modules.node_documentation.infra.repositories import NodePackageDocumentationRepository
from src.node_dsl._init_nodes import discover_node_classes
from src.node_dsl.discovery import discover_extension_node_descriptors


def _write_manifest(root: Path) -> Path:
    nodes_dir = root / "backend" / "nodes"
    nodes_dir.mkdir(parents=True)
    (root / "backend" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        """
[project]
name = "sample"
version = "1.0.0"

[tool.dvt_extension]
name = "sample"

[tool.dvt_extension.backend]
nodes_dir = "backend/nodes"
""",
        encoding="utf-8",
    )
    return nodes_dir


def _write_package_node(nodes_dir: Path, *, manifest: str = "schema_version: 1\n") -> None:
    package = nodes_dir / "package_node"
    package.mkdir()
    (package / "node.py").write_text(
        "from src.node_dsl.base_node.base import BaseNode\n"
        "class PackageExtensionNode(BaseNode):\n"
        "    def process(self):\n"
        "        return None\n",
        encoding="utf-8",
    )
    (package / "__init__.py").write_text(
        "from .node import PackageExtensionNode\n"
        "NODE_CLASS = PackageExtensionNode\n"
        "__all__ = ['PackageExtensionNode']\n",
        encoding="utf-8",
    )
    (package / "node.yaml").write_text(manifest, encoding="utf-8")
    (package / "README.md").write_text("# Package extension\n", encoding="utf-8")
    (package / "README.ru.md").write_text("# Package extension RU\n", encoding="utf-8")


def _write_legacy_node(nodes_dir: Path) -> None:
    (nodes_dir / "legacy_node.py").write_text(
        "from src.node_dsl.base_node.base import BaseNode\n"
        "class LegacyExtensionNode(BaseNode):\n"
        "    def process(self):\n"
        "        return None\n",
        encoding="utf-8",
    )


def test_package_extension_reload_creates_fresh_class(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "sample"
    nodes_dir = _write_manifest(root)
    _write_package_node(nodes_dir)
    extension = loader.load_manifest(root, extension_name="sample")
    assert extension is not None
    monkeypatch.setattr(loader.config.EXTENSIONS, "AUTOLOAD", True)

    first_modules = loader.import_extension_nodes_for(extension)
    first_classes = discover_node_classes(first_modules, extensions={"sample": extension})
    second_modules = loader.import_extension_nodes_for(extension)
    second_classes = discover_node_classes(second_modules, extensions={"sample": extension})

    first = next(cls for cls in first_classes if cls.__name__ == "PackageExtensionNode")
    second = next(cls for cls in second_classes if cls.__name__ == "PackageExtensionNode")
    assert first is not second
    assert second.EXTENSION_NAME == "sample"
    loader.purge_extension_modules(extension)


def test_mixed_package_and_legacy_extension_discovery(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "sample"
    nodes_dir = _write_manifest(root)
    _write_package_node(nodes_dir)
    _write_legacy_node(nodes_dir)
    extension = loader.load_manifest(root, extension_name="sample")
    assert extension is not None
    monkeypatch.setattr(loader.config.EXTENSIONS, "AUTOLOAD", True)

    modules = loader.import_extension_nodes_for(extension)
    classes = discover_node_classes(modules, extensions={"sample": extension})

    assert {cls.__name__ for cls in classes} == {"PackageExtensionNode", "LegacyExtensionNode"}
    loader.purge_extension_modules(extension)


@pytest.mark.asyncio
async def test_package_extension_documentation_uses_colocated_resources(
    monkeypatch, tmp_path: Path
) -> None:
    root = tmp_path / "sample"
    nodes_dir = _write_manifest(root)
    _write_package_node(nodes_dir)
    extension = loader.load_manifest(root, extension_name="sample")
    assert extension is not None
    monkeypatch.setattr(loader.config.EXTENSIONS, "AUTOLOAD", True)

    modules = loader.import_extension_nodes_for(extension)
    descriptors = discover_extension_node_descriptors(modules, extension=extension)
    descriptor = next(item for item in descriptors if item.node_name == "PackageExtensionNode")
    repository = NodePackageDocumentationRepository(
        package_catalog=lambda: {descriptor.node_name: descriptor}
    )

    english = await repository.get(node_name="PackageExtensionNode", locale="en")
    russian = await repository.get(node_name="PackageExtensionNode", locale="ru")

    assert english is not None
    assert english.content == "# Package extension\n"
    assert russian is not None
    assert russian.content == "# Package extension RU\n"
    loader.purge_extension_modules(extension)


def test_broken_package_extension_isolated_and_strict_raises(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "sample"
    nodes_dir = _write_manifest(root)
    _write_package_node(nodes_dir, manifest="schema_version: 2\n")
    monkeypatch.setattr(runtime.config.EXTENSIONS, "EXTENSIONS_DATA_DIR", tmp_path)
    monkeypatch.setattr(runtime.config.EXTENSIONS, "AUTOLOAD", True)
    monkeypatch.setattr(runtime.config.APP, "VERSION", "")
    spec = ExtensionRuntimeSpec(name="sample", root_dir=root)

    report = runtime.load_all_extension_runtimes([spec])
    assert report.loaded == {}
    assert "sample" in report.failures

    with pytest.raises(ExtensionRuntimeLoadError):
        runtime.load_all_extension_runtimes(
            [spec], strict_extension_names=frozenset({"sample"})
        )
    registry.clear()
