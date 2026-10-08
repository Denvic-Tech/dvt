"""Статическая таблица нод, которые читают или пишут таблицы БД, и их локаторных входов."""

from __future__ import annotations

from dataclasses import dataclass

from ..types import LinkDirection, LocatorKind


@dataclass(frozen=True, slots=True)
class NodeLocatorSpec:
    node_name: str
    direction: LinkDirection
    kind: LocatorKind
    connection_input: str = "connection"
    table_input: str = "table_name"
    schema_input: str = "schema_name"
    database_input: str = "database_name"
    sql_input: str = "sql_code"
    mode_input: str = "mode"
    manual_variables_input: str = "manual_variables"

    @property
    def explicit_inputs(self) -> tuple[str, str, str]:
        return (self.table_input, self.schema_input, self.database_input)


def _explicit(name: str, direction: LinkDirection) -> NodeLocatorSpec:
    return NodeLocatorSpec(node_name=name, direction=direction, kind=LocatorKind.EXPLICIT)


def _sql(name: str) -> NodeLocatorSpec:
    return NodeLocatorSpec(node_name=name, direction=LinkDirection.READ, kind=LocatorKind.SQL)


NODE_LOCATOR_SPECS: dict[str, NodeLocatorSpec] = {
    spec.node_name: spec
    for spec in (
        _explicit("ReadTableFromDBV3", LinkDirection.READ),
        _explicit("WriteDataFrameToDB", LinkDirection.WRITE),
        _explicit("WriteDataFrameToDBV2", LinkDirection.WRITE),
        _explicit("WriteDataFrameToDBV3", LinkDirection.WRITE),
        _explicit("WriteDataFrameToDBV4", LinkDirection.WRITE),
        _explicit("CreateTable", LinkDirection.WRITE),
        _sql("ReadQueryFromDBV3"),
        _sql("ExecuteSQL"),
        NodeLocatorSpec(
            node_name="ReadVariablesFromDB",
            direction=LinkDirection.READ,
            kind=LocatorKind.VARIABLES,
        ),
    )
}

CONNECTION_SOURCE_NODES: dict[str, str] = {
    # класс ноды-источника connection'а -> имя входа с идентификатором сохранённого connection'а
    "GetExistDBConnection": "connection_id",
}

READ_VARIABLES_DEFAULT_MODE = "manual"
READ_VARIABLES_SQL_MODE = "sql"
