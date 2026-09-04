from types import SimpleNamespace

import pytest

from src.node_dsl import _init_nodes as init_nodes_module
from src.node_dsl.base_node.base import BaseNode
from src.node_dsl.discovery.types import NodePackageDescriptor


def test_clear_registries_calls_all_registries(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(init_nodes_module.nodes_registry, "clear", lambda: calls.append("nodes"))
    monkeypatch.setattr(init_nodes_module.definitions_registry, "clear", lambda: calls.append("definitions"))
    monkeypatch.setattr(init_nodes_module.hooks_registry, "clear", lambda: calls.append("hooks"))
    monkeypatch.setattr(init_nodes_module.packages_registry, "clear", lambda: calls.append("packages"))

    init_nodes_module._clear_registries()

    assert calls == ["nodes", "definitions", "hooks", "packages"]


def test_rebuild_preserves_builtin_class_identity_and_public_module() -> None:
    from src.nodes.tool.execute_project import ExecuteProject

    original_snapshot = init_nodes_module._snapshot_registries()
    try:
        init_nodes_module.init_nodes()
        first_registered = init_nodes_module.nodes_registry.NODE_CLASSES["ExecuteProject"]
        init_nodes_module.rebuild_node_registries()
        second_registered = init_nodes_module.nodes_registry.NODE_CLASSES["ExecuteProject"]
        definition = init_nodes_module.definitions_registry.NODE_DEFINITIONS["ExecuteProject"]["default"]
        descriptor = init_nodes_module.packages_registry.NODE_PACKAGES["ExecuteProject"]

        assert first_registered is ExecuteProject
        assert second_registered is first_registered
        assert second_registered.__module__ == "src.nodes.tool.execute_project.node"
        assert definition.python_module == "src.nodes.tool.execute_project"
        assert descriptor.package_module == "src.nodes.tool.execute_project"
    finally:
        init_nodes_module._restore_registries(original_snapshot, restore_bootstrap_state=True)


def test_registry_snapshot_restores_package_catalog() -> None:
    original = init_nodes_module._snapshot_registries()
    try:
        init_nodes_module.init_nodes()
        snapshot = init_nodes_module._snapshot_registries()
        expected = dict(snapshot.node_packages)
        init_nodes_module.packages_registry.NODE_PACKAGES.clear()
        init_nodes_module._restore_registries(snapshot)
        assert expected == init_nodes_module.packages_registry.NODE_PACKAGES
    finally:
        init_nodes_module._restore_registries(original, restore_bootstrap_state=True)


def test_init_nodes_restores_previous_registry_after_fatal_registration_failure(monkeypatch) -> None:
    original = init_nodes_module._snapshot_registries()
    try:
        init_nodes_module.init_nodes()
        previous = init_nodes_module._snapshot_registries()

        def fail(_descriptors):
            init_nodes_module.nodes_registry.NODE_CLASSES.clear()
            init_nodes_module.definitions_registry.NODE_DEFINITIONS.clear()
            init_nodes_module.hooks_registry.HOOKS_REGISTRY.clear()
            init_nodes_module.packages_registry.NODE_PACKAGES.clear()
            raise RuntimeError("broken builtin")

        monkeypatch.setattr(init_nodes_module, "register_node_packages", fail)
        with pytest.raises(RuntimeError, match="broken builtin"):
            init_nodes_module.init_nodes()

        assert previous.node_classes == init_nodes_module.nodes_registry.NODE_CLASSES
        assert previous.node_definitions == init_nodes_module.definitions_registry.NODE_DEFINITIONS
        assert previous.hooks == init_nodes_module.hooks_registry.HOOKS_REGISTRY
        assert previous.node_packages == init_nodes_module.packages_registry.NODE_PACKAGES
    finally:
        init_nodes_module._restore_registries(original, restore_bootstrap_state=True)


def test_extension_registration_failure_rolls_back_all_extension_registries(monkeypatch) -> None:
    class BuiltinTxNode(BaseNode):
        def process(self) -> None:
            return None

    class BrokenExtensionTxNode(BaseNode):
        def process(self) -> None:
            return None

    class GoodExtensionTxNode(BaseNode):
        def process(self) -> None:
            return None

    def descriptor(
        node_cls: type[BaseNode], *, extension_name: str | None = None
    ) -> NodePackageDescriptor:
        return NodePackageDescriptor(
            node_name=node_cls.__name__,
            node_cls=node_cls,
            package_module=node_cls.__module__,
            package_path=None,
            manifest=None,
            provider="builtin" if extension_name is None else "extension",
            extension_name=extension_name,
            extension_version=None if extension_name is None else "1.0.0",
            legacy=extension_name is not None,
        )

    builtin = descriptor(BuiltinTxNode)
    broken = descriptor(BrokenExtensionTxNode, extension_name="bad")
    good = descriptor(GoodExtensionTxNode, extension_name="good")
    original_snapshot = init_nodes_module._snapshot_registries()
    original_build = init_nodes_module.definitions_registry.build

    def discover_extension(_modules, *, extension):
        return [broken] if extension.name == "bad" else [good]

    def build_definition(node_cls, **kwargs):
        if node_cls is BrokenExtensionTxNode:
            raise RuntimeError("broken extension definition")
        return original_build(node_cls, **kwargs)

    monkeypatch.setattr(
        init_nodes_module,
        "discover_builtin_node_packages",
        lambda _nodes_dir: [builtin],
    )
    monkeypatch.setattr(
        init_nodes_module,
        "discover_extension_node_descriptors",
        discover_extension,
    )
    monkeypatch.setattr(init_nodes_module.definitions_registry, "build", build_definition)

    try:
        result = init_nodes_module.init_nodes(
            extension_modules={"bad": {}, "good": {}},
            extensions={
                "bad": SimpleNamespace(name="bad"),
                "good": SimpleNamespace(name="good"),
            },
        )

        assert "bad" in result.extension_failures
        expected_names = {"BuiltinTxNode", "GoodExtensionTxNode"}
        assert set(init_nodes_module.nodes_registry.NODE_CLASSES) == expected_names
        assert set(init_nodes_module.definitions_registry.NODE_DEFINITIONS) == expected_names
        assert set(init_nodes_module.hooks_registry.HOOKS_REGISTRY) == expected_names
        assert set(init_nodes_module.packages_registry.NODE_PACKAGES) == expected_names
        assert "BrokenExtensionTxNode" not in init_nodes_module.nodes_registry.NODE_CLASSES
        assert "BrokenExtensionTxNode" not in init_nodes_module.packages_registry.NODE_PACKAGES
    finally:
        init_nodes_module._restore_registries(
            original_snapshot,
            restore_bootstrap_state=True,
        )


def test_node_name_conflicts_reject_all_extension_owners() -> None:
    builtin = type("BuiltinNode", (), {})
    first_shared = type("SharedNode", (), {})
    second_shared = type("SharedNode", (), {})
    builtin_conflict = type("BuiltinNode", (), {})

    failures = init_nodes_module._find_node_name_conflicts(
        [builtin],
        {
            "first": [first_shared, builtin_conflict],
            "second": [second_shared],
        },
    )

    assert set(failures) == {"first", "second"}
    assert "conflicts with a builtin node" in failures["first"]
    assert "SharedNode" in failures["first"]
    assert "SharedNode" in failures["second"]
