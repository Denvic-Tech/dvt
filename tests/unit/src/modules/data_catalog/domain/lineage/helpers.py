"""Общие фикстуры lineage-тестов: типы портов встроенных нод и сборка снэпшотов графа."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.modules.data_catalog.domain import (
    ColumnLineage,
    GraphEdge,
    GraphInputValue,
    GraphNode,
    LineageOp,
    LineageRef,
    NodePortTypes,
    PortColumns,
    ProjectGraphSnapshot,
    ProjectStampSource,
)

DF_IN_OUT = NodePortTypes(dataframe_inputs=frozenset({"df"}), dataframe_outputs=("output",))

PORT_TYPES: dict[str, NodePortTypes] = {
    "ReadTableFromDBV3": NodePortTypes(dataframe_outputs=("output",)),
    "ReadQueryFromDBV3": NodePortTypes(dataframe_outputs=("output",)),
    "ExecuteSQL": NodePortTypes(dataframe_outputs=("output",)),
    "LoadParquet": NodePortTypes(dataframe_outputs=("output",)),
    "DataFrameFilter": NodePortTypes(
        dataframe_inputs=frozenset({"df"}), dataframe_outputs=("output", "inverted_output")
    ),
    "DataFrameJoin": NodePortTypes(
        dataframe_inputs=frozenset({"left", "right"}),
        dataframe_outputs=("output",),
        defaults={"how": "left"},
    ),
    "DataFrameUnion": NodePortTypes(dataframe_inputs=frozenset({"df1", "df2"}), dataframe_outputs=("output",)),
    "DataFrameLagColumns": NodePortTypes(
        dataframe_inputs=frozenset({"df"}), dataframe_outputs=("output",), defaults={"lag_steps": 1}
    ),
    "DataFrameSplitColumn": NodePortTypes(
        dataframe_inputs=frozenset({"df"}),
        dataframe_outputs=("output",),
        defaults={"max_splits": 1, "drop_source": False},
    ),
    "SetColumnToDataFrame": NodePortTypes(
        dataframe_inputs=frozenset({"df"}), column_inputs=frozenset({"column_data"}), dataframe_outputs=("output",)
    ),
    "WriteDataFrameToDBV4": NodePortTypes(dataframe_inputs=frozenset({"df"})),
    "DataFrameSelectVariables": NodePortTypes(dataframe_inputs=frozenset({"df"})),
}

for _name in (
    "DataFrameQuery",
    "DataFrameSortValues",
    "DataFrameFillNA",
    "DataFrameCastColumnType",
    "DataFrameNumericNormalizer",
    "DataFrameSetIndex",
    "DataFrameSelectColumns",
    "DataFrameDropColumns",
    "DataFrameRenameColumns",
    "DataFrameGroupByAgg",
    "DataFrameUnpivot",
    "GetCurrentDateTime",
    "DataFramePivot",
    "DataFrameExecCode",
    "DataFrameRegexReplace",
    "DataFrameReplaceValues",
    "DataFrameSetTimezone",
    "DataFrameConvertToPeriodStart",
    "AddTimeDeltaToDataFrame",
    "DataFrameAddColumnByExpression",
    "ConvertVariablesToDataFrame",
):
    PORT_TYPES.setdefault(_name, DF_IN_OUT)


def port_types(name: str) -> NodePortTypes | None:
    return PORT_TYPES.get(name)


def node(ui_id: str, name: str, **inputs: Any) -> GraphNode:
    return GraphNode(
        ui_id=ui_id,
        name=name,
        inputs={key: value if isinstance(value, GraphInputValue) else GraphInputValue.const(value) for key, value in inputs.items()},
    )


def edge(source: str, target: str, *, output: str = "output", input: str = "df") -> GraphEdge:
    return GraphEdge(
        source=source,
        target=target,
        source_handle=f"output-{output}",
        target_handle=f"input-{input}",
    )


def snapshot(*nodes: GraphNode, edges: tuple[GraphEdge, ...] = ()) -> ProjectGraphSnapshot:
    return ProjectGraphSnapshot(
        stamp_source=ProjectStampSource(project_id="p1", organization_id="org", graph_revision=1),
        nodes=nodes,
        edges=edges,
    )


def source_seed(dataset_id: str, *names: str) -> PortColumns:
    return PortColumns(
        columns=tuple(
            ColumnLineage(
                name=name,
                op=LineageOp.SOURCE,
                deps=(LineageRef.dataset_field(dataset_id, f"f-{name}"),),
                details={"template": "lineage.source.table", "field": name},
            )
            for name in names
        )
    )


def by_name(port) -> Mapping[str, ColumnLineage]:
    return {column.name: column for column in port.columns}
