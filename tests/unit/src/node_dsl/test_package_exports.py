import pytest
from sqlmodel import Session, create_engine

import src.node_dsl as node_dsl
from src.exceptions import NodeNotFoundError
from src.models.extension import ExtensionRecord
from src.node_dsl.base_node import BaseNode
from src.node_dsl.exceptions import NodeDSLException, NodeValidationError
from src.node_dsl.field import InputField, OutputField
from src.node_dsl.node_mixins import NodeFieldsMixin
from src.node_dsl.node_typing import IO
from src.node_dsl.registry import (
    definitions as definitions_registry,
    hooks as hooks_registry,
    nodes as nodes_registry,
)


def test_package_exports_are_static() -> None:
    assert node_dsl.InputField is InputField
    assert node_dsl.OutputField is OutputField
    assert node_dsl.IO is IO
    assert node_dsl.BaseNode is BaseNode
    assert node_dsl.NodeFieldsMixin is NodeFieldsMixin
    assert node_dsl.NodeValidationError is NodeValidationError
    assert node_dsl.NodeDSLException is NodeDSLException
    assert node_dsl.get_all_nodes is node_dsl.registry.get_all_nodes
    assert node_dsl.get_all_definitions is node_dsl.registry.get_all_definitions
    assert node_dsl.get_all_hooks is node_dsl.registry.get_all_hooks
    assert "BaseNode" in node_dsl.__all__
    assert "NodeFieldsMixin" in node_dsl.__all__
    assert "get_all_definitions" in node_dsl.__all__
    assert "FileConnectionInputMixin" in node_dsl.__all__


def test_get_all_nodes_bootstraps_registry_read(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(nodes_registry, "ensure_bootstrapped", lambda **_: calls.append("init"))

    node_dsl.get_all_nodes()
    assert calls == ["init"]


def test_missing_node_does_not_force_destructive_registry_rebuild(monkeypatch) -> None:
    bootstrap_calls: list[dict] = []
    extension_node = type("ExtensionNode", (), {})

    monkeypatch.setattr(
        nodes_registry,
        "NODE_CLASSES",
        {"ExtensionNode": extension_node},
    )
    monkeypatch.setattr(
        nodes_registry,
        "ensure_bootstrapped",
        lambda **kwargs: bootstrap_calls.append(kwargs),
    )

    with pytest.raises(NodeNotFoundError, match="MissingNode"):
        nodes_registry.get("MissingNode")

    assert nodes_registry.NODE_CLASSES == {"ExtensionNode": extension_node}
    assert len(bootstrap_calls) == 1
    assert bootstrap_calls[0].get("force") is not True


def test_extension_node_lookup_reads_sqlmodel_record(monkeypatch) -> None:
    sqlite_engine = create_engine("sqlite://")
    ExtensionRecord.__table__.create(sqlite_engine)

    with Session(sqlite_engine) as session:
        session.add(
            ExtensionRecord(
                name="test-extension",
                display_name="Test extension",
                is_installed=True,
                is_enabled=True,
            )
        )
        session.commit()

    extension_node = type(
        "ExtensionNode",
        (),
        {"EXTENSION_NAME": "test-extension"},
    )
    monkeypatch.setattr(nodes_registry, "engine", sqlite_engine)
    monkeypatch.setattr(
        nodes_registry,
        "NODE_CLASSES",
        {"ExtensionNode": extension_node},
    )

    assert nodes_registry.get("ExtensionNode") is extension_node


def test_get_all_definitions_bootstraps_registry_read(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(definitions_registry, "ensure_bootstrapped", lambda **_: calls.append("init"))

    node_dsl.get_all_definitions()
    assert calls == ["init"]


def test_get_all_hooks_bootstraps_registry_read(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(hooks_registry, "ensure_bootstrapped", lambda **_: calls.append("init"))

    node_dsl.get_all_hooks()
    assert calls == ["init"]
