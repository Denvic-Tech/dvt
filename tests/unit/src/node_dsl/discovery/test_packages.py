from __future__ import annotations

from pathlib import Path

import pytest

from src.node_dsl import _init_nodes as init_nodes_module
from src.node_dsl.discovery import NodePackageDiscoveryError, discover_builtin_node_packages

import config


def _write_package(root: Path, *, name: str = "sample", init_source: str | None = None) -> Path:
    category = root / "category"
    category.mkdir(parents=True, exist_ok=True)
    (root / "__init__.py").write_text("", encoding="utf-8")
    (category / "__init__.py").write_text("", encoding="utf-8")
    package = category / name
    package.mkdir()
    (package / "node.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    (package / "node.py").write_text(
        "from src.node_dsl.base_node.base import BaseNode\n"
        "class SampleNode(BaseNode):\n"
        "    def process(self):\n"
        "        return None\n",
        encoding="utf-8",
    )
    (package / "__init__.py").write_text(
        init_source
        or "from .node import SampleNode\nNODE_CLASS = SampleNode\n__all__ = ['SampleNode']\n",
        encoding="utf-8",
    )
    return package


def test_builtin_discovery_uses_only_direct_node_yaml(monkeypatch, tmp_path: Path) -> None:
    package_root = tmp_path / "testnodes"
    package = _write_package(package_root)
    examples = package / "examples"
    examples.mkdir()
    (examples / "example.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    descriptors = discover_builtin_node_packages(package_root, package_prefix="testnodes")

    assert [item.node_name for item in descriptors] == ["SampleNode"]
    assert descriptors[0].package_module == "testnodes.category.sample"


def test_builtin_discovery_ignores_private_directory(monkeypatch, tmp_path: Path) -> None:
    package_root = tmp_path / "testnodes_private"
    _write_package(package_root)
    shared = package_root / "category" / "_shared"
    shared.mkdir()
    (shared / "helper.py").write_text("raise RuntimeError('must not import')\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    descriptors = discover_builtin_node_packages(package_root, package_prefix="testnodes_private")

    assert len(descriptors) == 1


def test_invalid_builtin_layout_is_fatal_during_registry_bootstrap(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "nodes"
    category = root / "category"
    category.mkdir(parents=True)
    (category / "__init__.py").write_text("", encoding="utf-8")
    (category / "bad.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(config.PROJECT, "NODES_DIR", root)

    with pytest.raises(NodePackageDiscoveryError, match="Public flat node module"):
        init_nodes_module.init_nodes(extension_modules={}, extensions={})


def test_public_flat_module_is_fatal(tmp_path: Path) -> None:
    root = tmp_path / "nodes"
    category = root / "category"
    category.mkdir(parents=True)
    (category / "__init__.py").write_text("", encoding="utf-8")
    (category / "bad.py").write_text("", encoding="utf-8")

    with pytest.raises(NodePackageDiscoveryError, match="Public flat node module"):
        discover_builtin_node_packages(root, package_prefix="unused")


def test_public_directory_without_manifest_is_fatal(tmp_path: Path) -> None:
    root = tmp_path / "nodes"
    category = root / "category"
    bad = category / "bad"
    bad.mkdir(parents=True)
    (category / "__init__.py").write_text("", encoding="utf-8")
    (bad / "__init__.py").write_text("", encoding="utf-8")

    with pytest.raises(NodePackageDiscoveryError, match=r"missing node\.yaml"):
        discover_builtin_node_packages(root, package_prefix="unused")


def test_package_without_init_is_fatal(tmp_path: Path) -> None:
    root = tmp_path / "nodes"
    category = root / "category"
    bad = category / "bad"
    bad.mkdir(parents=True)
    (category / "__init__.py").write_text("", encoding="utf-8")
    (bad / "node.yaml").write_text("schema_version: 1\n", encoding="utf-8")

    with pytest.raises(NodePackageDiscoveryError, match=r"missing __init__\.py"):
        discover_builtin_node_packages(root, package_prefix="unused")


def test_package_without_node_class_is_fatal(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "testnodes_missing_entrypoint"
    _write_package(root, init_source="from .node import SampleNode\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(NodePackageDiscoveryError, match=r"does not export NODE_CLASS"):
        discover_builtin_node_packages(root, package_prefix="testnodes_missing_entrypoint")


def test_node_class_pointing_outside_package_is_fatal(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "testnodes_outside"
    _write_package(
        root,
        init_source=(
            "from src.nodes.transform.df_join import DataFrameJoin\n"
            "NODE_CLASS = DataFrameJoin\n"
        ),
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(NodePackageDiscoveryError, match="does not belong"):
        discover_builtin_node_packages(root, package_prefix="testnodes_outside")


def test_node_class_not_a_class_is_fatal(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "testnodes_not_class"
    _write_package(root, init_source="NODE_CLASS = 42\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(NodePackageDiscoveryError, match="must be a Python class"):
        discover_builtin_node_packages(root, package_prefix="testnodes_not_class")


def test_node_class_not_base_node_is_fatal(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "testnodes_not_node"
    _write_package(root, init_source="class NotNode: pass\nNODE_CLASS = NotNode\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(NodePackageDiscoveryError, match="concrete BaseNode subclass"):
        discover_builtin_node_packages(root, package_prefix="testnodes_not_node")


def test_abstract_node_class_is_fatal(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "testnodes_abstract"
    _write_package(
        root,
        init_source=(
            "from abc import abstractmethod\n"
            "from src.node_dsl.base_node.base import BaseNode\n"
            "class AbstractNode(BaseNode):\n"
            "    @abstractmethod\n"
            "    def process(self): ...\n"
            "NODE_CLASS = AbstractNode\n"
        ),
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(NodePackageDiscoveryError, match="must not be abstract"):
        discover_builtin_node_packages(root, package_prefix="testnodes_abstract")
