"""Снэпшот сохранённого графа проекта в доменных терминах (без ORM и транспорта)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

INPUT_HANDLE_PREFIX = "input-"
OUTPUT_HANDLE_PREFIX = "output-"

InputValueKind = Literal["const", "expr", "link"]


@dataclass(frozen=True, slots=True)
class GraphInputValue:
    kind: InputValueKind
    value: Any = None
    expression_kind: str | None = None
    link_node_id: str | None = None
    link_output: str | None = None

    @classmethod
    def const(cls, value: Any) -> GraphInputValue:
        return cls(kind="const", value=value)

    @classmethod
    def expr(cls, expression: str, expression_kind: str) -> GraphInputValue:
        return cls(kind="expr", value=expression, expression_kind=expression_kind)

    @classmethod
    def link(cls, node_id: str, output_name: str) -> GraphInputValue:
        return cls(kind="link", link_node_id=node_id, link_output=output_name)


@dataclass(frozen=True, slots=True)
class GraphNode:
    ui_id: str
    name: str
    inputs: Mapping[str, GraphInputValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source: str
    target: str
    source_handle: str | None = None
    target_handle: str | None = None

    @property
    def target_input(self) -> str | None:
        return _strip_prefix(self.target_handle, INPUT_HANDLE_PREFIX)

    @property
    def source_output(self) -> str | None:
        return _strip_prefix(self.source_handle, OUTPUT_HANDLE_PREFIX)


def _strip_prefix(handle: str | None, prefix: str) -> str | None:
    if handle is None:
        return None
    if handle.startswith(prefix):
        return handle[len(prefix):]
    return handle


@dataclass(frozen=True, slots=True)
class ProjectStampSource:
    project_id: str
    organization_id: str
    graph_revision: int
    variables: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ProjectGraphSnapshot:
    stamp_source: ProjectStampSource
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()

    @property
    def project_id(self) -> str:
        return self.stamp_source.project_id

    @property
    def organization_id(self) -> str:
        return self.stamp_source.organization_id

    @property
    def graph_revision(self) -> int:
        return self.stamp_source.graph_revision


@dataclass(frozen=True, slots=True)
class ConnectionLocator:
    """Несекретные координаты сохранённого connection'а."""

    id: str
    dialect: str
    host: str
    port: int | None
    database: str | None
    revision: str
    deleted: bool = False
