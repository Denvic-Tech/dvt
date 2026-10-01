"""Shared graph construction; callers provide real or unit-test connections."""
from datetime import UTC, datetime

from src.modules.db_connection import ConnectionRecord
from src.node_dsl import KafkaConnectionRecord
from src.node_dsl.core.input_values import (
    NodeInputConstantValue as Const,
    NodeInputExpressionValue as Expr,
    NodeInputLinkValue as Link,
)
from src.node_dsl.registry import definitions, hooks, nodes
from src.nodes.extract.read_kafka_messages import ReadKafkaMessages
from src.nodes.tool.commit_kafka_offsets import CommitKafkaOffsets
from src.nodes.transform.df_filter import DataFrameFilter
from src.nodes.write.write_df_to_db_v3 import WriteDataFrameToDBV3
from src.pipeline.execution_mode import PipelineExecutionMode
from src.pipeline.processor import PipelineProcessor
from src.schemas.internal import NodeData, ProjectSettings, ProjectVariables, TaskInternal


def kafka_connection(properties, secrets=None):
    now = datetime.now(UTC)
    return KafkaConnectionRecord(ConnectionRecord(
        id="test-connection", name="Kafka test", kind="queue", type="kafka",
        created_at=now, updated_at=now, properties=properties, secrets=secrets or {},
    ))


def register_nodes(*classes):
    for cls in classes:
        if cls.__name__ not in nodes.get_all():
            nodes.add(cls)
        if cls.__name__ not in definitions.NODE_DEFINITIONS:
            definitions.build(cls)
        hooks.build(cls)


def graph(connection, engine, topic, group, tables):
    register_nodes(ReadKafkaMessages, CommitKafkaOffsets, DataFrameFilter, WriteDataFrameToDBV3)
    pipeline = {
        "read": NodeData(name="ReadKafkaMessages", store_enabled=True, inputs={
            "connection": Const(value=connection), "topic": Const(value=topic),
            "group_id": Const(value=group), "max_messages": Const(value=3),
            "rows_per_partition": Const(value=1),
        }),
        "filter": NodeData(name="DataFrameFilter", store_enabled=True, inputs={
            "df": Link(node_id="read", output_name="output"),
            "conditions": Const(value={
                "kind": "condition", "left": {"type": "column", "column": "value"},
                "operator": "!=", "right": {"type": "literal", "value": "drop"},
            }),
        }),
    }
    for index, table in enumerate(tables):
        pipeline[f"write{index}"] = NodeData(name="WriteDataFrameToDBV3", inputs={
            "connection": Const(value=engine),
            "df": Link(node_id="filter", output_name="output"),
            "table_name": Const(value=table),
        })
    pipeline["commit"] = NodeData(name="CommitKafkaOffsets", store_enabled=True, inputs={
        "connection": Const(value=connection),
        "offsets": Expr(value="kafka_offsets", expression_kind="single"),
        "input_variables": [Link(node_id="read", output_name="output_variables")],
        "signal_in": [Link(node_id=f"write{i}", output_name="signal_out")
                      for i in range(len(tables))],
    })
    return pipeline


def processor(pipeline, *, project="kafka-commit", run="run", mode=PipelineExecutionMode.FULL,
              targets=("commit",), **kwargs):
    return PipelineProcessor(task=TaskInternal(
        project_id=project, task_id=run, user_id="u", pipeline=pipeline,
        target_nodes=list(targets), graph_revision=1, mode=mode,
        project_settings=ProjectSettings(store_enabled=True, workers_count=2, ttl_time=600),
        project_variables=ProjectVariables(variables={}), license_type="000",
    ), **kwargs)
