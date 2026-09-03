from pathlib import Path

from src.node_dsl import _init_nodes as init_nodes_module


class _FakeNode:
    __name__ = "FakeExtensionNode"
    __module__ = "dvt_extensions.sample.nodes.fake"
    EXTENSION_NAME = "sample"
    EXTENSION_VERSION = "1.0.0"


class _BuiltinNode:
    __name__ = "BuiltinNode"
    __module__ = "src.nodes.fake"
    EXTENSION_NAME = None
    EXTENSION_VERSION = None


class _GoodExtensionNode:
    __name__ = "GoodExtensionNode"


class _BadExtensionNode:
    __name__ = "BadExtensionNode"


def test_is_node_class_active_skips_removed_extension(monkeypatch, tmp_path: Path) -> None:
    node_file = tmp_path / "extensions" / "sample" / "nodes" / "fake.py"
    node_file.parent.mkdir(parents=True)
    node_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        init_nodes_module,
        "get_all_extensions",
        dict,
    )
    monkeypatch.setattr(init_nodes_module.inspect, "getfile", lambda cls: str(node_file))

    assert init_nodes_module._is_node_class_active(_FakeNode) is False


def test_is_node_class_active_keeps_builtin_node(monkeypatch, tmp_path: Path) -> None:
    node_file = tmp_path / "src" / "nodes" / "fake.py"
    node_file.parent.mkdir(parents=True)
    node_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        init_nodes_module,
        "get_all_extensions",
        dict,
    )
    monkeypatch.setattr(init_nodes_module.inspect, "getfile", lambda cls: str(node_file))

    assert init_nodes_module._is_node_class_active(_BuiltinNode) is True


def test_clear_registries_calls_all_registries(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(init_nodes_module.nodes_registry, "clear", lambda: calls.append("nodes"))
    monkeypatch.setattr(init_nodes_module.definitions_registry, "clear", lambda: calls.append("definitions"))
    monkeypatch.setattr(init_nodes_module.hooks_registry, "clear", lambda: calls.append("hooks"))

    init_nodes_module._clear_registries()

    assert calls == ["nodes", "definitions", "hooks"]


def test_rebuild_imports_builtin_nodes_once(monkeypatch) -> None:
    import_calls: list[Path] = []
    original_snapshot = init_nodes_module._snapshot_registries()

    try:
        monkeypatch.setattr(
            init_nodes_module,
            "import_nodes",
            lambda directory: import_calls.append(directory) or {"fake": object()},
        )
        monkeypatch.setattr(
            init_nodes_module,
            "discover_node_classes",
            lambda *_args, **_kwargs: [_BuiltinNode],
        )
        monkeypatch.setattr(
            init_nodes_module.definitions_registry,
            "build",
            lambda cls: init_nodes_module.definitions_registry.NODE_DEFINITIONS.__setitem__(
                cls.__name__, {"default": object()}
            ),
        )
        monkeypatch.setattr(
            init_nodes_module.hooks_registry,
            "build",
            lambda cls: init_nodes_module.hooks_registry.HOOKS_REGISTRY.__setitem__(cls.__name__, {}),
        )

        init_nodes_module.rebuild_node_registries()

        assert import_calls == [Path(init_nodes_module.config.PROJECT.NODES_DIR)]
    finally:
        init_nodes_module._restore_registries(
            original_snapshot, restore_bootstrap_state=True
        )


def test_rebuild_preserves_canonical_builtin_class_identity() -> None:
    from src.nodes.tool.execute_project import ExecuteProject

    original_snapshot = init_nodes_module._snapshot_registries()

    try:
        init_nodes_module.init_nodes()
        first_registered_class = init_nodes_module.nodes_registry.NODE_CLASSES["ExecuteProject"]

        init_nodes_module.rebuild_node_registries()
        second_registered_class = init_nodes_module.nodes_registry.NODE_CLASSES["ExecuteProject"]

        assert first_registered_class is ExecuteProject
        assert second_registered_class is first_registered_class
        assert second_registered_class.__module__ == "src.nodes.tool.execute_project"
    finally:
        init_nodes_module._restore_registries(
            original_snapshot, restore_bootstrap_state=True
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


def test_init_nodes_isolates_extension_registration_failure(monkeypatch) -> None:
    original_snapshot = init_nodes_module._snapshot_registries()

    monkeypatch.setattr(init_nodes_module, "import_nodes", lambda _directory: {"builtin": object()})

    def discover(_modules, *, extensions):
        if not extensions:
            return [_BuiltinNode]
        extension_name = next(iter(extensions))
        return {
            "bad": [_BadExtensionNode],
            "good": [_GoodExtensionNode],
        }[extension_name]

    def register(classes) -> None:
        for node_cls in classes:
            node_name = node_cls.__name__
            init_nodes_module.nodes_registry.NODE_CLASSES[node_name] = node_cls
            init_nodes_module.definitions_registry.NODE_DEFINITIONS[node_name] = {
                "default": object()
            }
            init_nodes_module.hooks_registry.HOOKS_REGISTRY[node_name] = {}
            if node_cls is _BadExtensionNode:
                raise ValueError("invalid extension node")

    monkeypatch.setattr(init_nodes_module, "discover_node_classes", discover)
    monkeypatch.setattr(init_nodes_module, "register_node_classes", register)

    try:
        result = init_nodes_module.init_nodes(
            extension_modules={"bad": {}, "good": {}},
            extensions={"bad": object(), "good": object()},
        )

        assert "bad" in result.extension_failures
        assert _BadExtensionNode.__name__ not in init_nodes_module.nodes_registry.NODE_CLASSES
        assert _GoodExtensionNode.__name__ in init_nodes_module.nodes_registry.NODE_CLASSES
    finally:
        init_nodes_module._restore_registries(
            original_snapshot, restore_bootstrap_state=True
        )


def test_init_nodes_restores_previous_registry_after_fatal_failure(monkeypatch) -> None:
    original_snapshot = init_nodes_module._snapshot_registries()
    sentinel = type("PreviouslyRegisteredNode", (), {})
    init_nodes_module.nodes_registry.NODE_CLASSES.clear()
    init_nodes_module.nodes_registry.NODE_CLASSES["PreviouslyRegisteredNode"] = sentinel
    init_nodes_module.definitions_registry.NODE_DEFINITIONS.clear()
    init_nodes_module.definitions_registry.NODE_DEFINITIONS["PreviouslyRegisteredNode"] = {
        "default": object()
    }
    init_nodes_module.hooks_registry.HOOKS_REGISTRY.clear()
    init_nodes_module.hooks_registry.HOOKS_REGISTRY["PreviouslyRegisteredNode"] = {}

    monkeypatch.setattr(init_nodes_module, "import_nodes", lambda _directory: {"builtin": object()})
    monkeypatch.setattr(
        init_nodes_module,
        "discover_node_classes",
        lambda *_args, **_kwargs: [_BuiltinNode],
    )
    monkeypatch.setattr(
        init_nodes_module,
        "register_node_classes",
        lambda _classes: (_ for _ in ()).throw(RuntimeError("broken builtin")),
    )

    try:
        try:
            init_nodes_module.init_nodes()
        except RuntimeError as exc:
            assert str(exc) == "broken builtin"
        else:
            raise AssertionError("Expected fatal registry rebuild failure")

        assert init_nodes_module.nodes_registry.NODE_CLASSES == {
            "PreviouslyRegisteredNode": sentinel
        }
        assert "PreviouslyRegisteredNode" in init_nodes_module.definitions_registry.NODE_DEFINITIONS
        assert "PreviouslyRegisteredNode" in init_nodes_module.hooks_registry.HOOKS_REGISTRY
    finally:
        init_nodes_module._restore_registries(
            original_snapshot, restore_bootstrap_state=True
        )
