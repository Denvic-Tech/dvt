"""Типы портов нод из реестра определений Node DSL без принудительного bootstrap на промахе."""

from __future__ import annotations

from typing import Any

from ...domain import NodePortTypeGateway, NodePortTypes


class NodeDslPortTypeGateway(NodePortTypeGateway):
    """Реестр импортируется лениво: модели каталога живут и в сервисах без реестра нод."""

    def __init__(self) -> None:
        self._cache: dict[str, NodePortTypes] = {}
        self._misses: set[str] = set()

    def get_port_types(self, node_name: str) -> NodePortTypes | None:
        cached = self._cache.get(node_name)
        if cached is not None:
            return cached
        if node_name in self._misses:
            return None

        from src.node_dsl.registry import definitions

        if not definitions.has(node_name):
            definitions.ensure_ready()
            if not definitions.has(node_name):
                self._misses.add(node_name)
                return None

        definition = definitions.get(node_name)
        types = _port_types(definition)
        self._cache[node_name] = types
        return types


def _port_types(definition: Any) -> NodePortTypes:
    from src.node_dsl.node_typing import IO

    dataframe_inputs: set[str] = set()
    column_inputs: set[str] = set()
    defaults: dict[str, Any] = {}
    for name, item in dict(getattr(definition, "input_definitions", {}) or {}).items():
        kinds = _io_kinds(getattr(item, "type", None))
        if IO.DATAFRAME in kinds:
            dataframe_inputs.add(name)
        elif IO.COLUMN in kinds:
            column_inputs.add(name)
        default = getattr(item, "default", None)
        if default is not None:
            defaults[name] = default

    dataframe_outputs: list[str] = []
    column_outputs: list[str] = []
    for name, item in dict(getattr(definition, "output_definitions", {}) or {}).items():
        kinds = _io_kinds(getattr(item, "type", None))
        if IO.DATAFRAME in kinds:
            dataframe_outputs.append(name)
        elif IO.COLUMN in kinds:
            column_outputs.append(name)

    return NodePortTypes(
        dataframe_inputs=frozenset(dataframe_inputs),
        dataframe_outputs=tuple(dataframe_outputs),
        column_inputs=frozenset(column_inputs),
        column_outputs=tuple(column_outputs),
        defaults=defaults,
    )


def _io_kinds(value: Any) -> set[Any]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        return set(value)
    return {value}
