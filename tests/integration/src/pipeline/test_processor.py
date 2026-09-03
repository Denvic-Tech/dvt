import asyncio

import dask.dataframe as dd
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from sqlalchemy import text
from tests.unit.src.pipeline.templates.df_drop_columns import get_drop_columns
from tests.unit.src.pipeline.templates.df_exec_code import get_exec_code
from tests.unit.src.pipeline.templates.df_filter import build_condition, get_filter
from tests.unit.src.pipeline.templates.df_join import get_join
from tests.unit.src.pipeline.templates.df_select_columns import get_select_columns
from tests.unit.src.pipeline.templates.load_excel import get_load_excel
from tests.unit.src.pipeline.templates.save_excel import get_save_excel

from core.metadata import get_df_metadata

from src.node_dsl.core.input_values import NodeInputConstantValue
from src.nodes.tool.create_table import CreateTable
from src.pipeline.execution_mode import PipelineExecutionMode
from src.pipeline.processor import PipelineProcessor
from src.schemas.internal import (
    NodeData,
    ProjectSettings,
    ProjectVariables,
    TaskInternal,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.docker_required]

PIPELINE_PROCESS_TIMEOUT_SEC = 60
DEFAULT_PROJECT_SETTINGS = ProjectSettings(
    store_enabled=True,
    ttl_time=10 * 60,
    workers_count=4,
)


def _get_node_df(processor: PipelineProcessor, node_id: str) -> pd.DataFrame:
    return processor.nodes_outputs[node_id]["output"].value.compute()


def _build_task(pipeline: dict[str, NodeData], target_nodes: list[str]) -> TaskInternal:
    return TaskInternal(
        project_id="proj-1",
        task_id="task-1",
        user_id="user-1",
        pipeline=pipeline,
        target_nodes=target_nodes,
        mode=PipelineExecutionMode.FULL,
        send_ws_messages=False,
        project_settings=DEFAULT_PROJECT_SETTINGS,
        project_variables=ProjectVariables(),
    )


async def _ensure_table(connection, table_name: str, df: dd.DataFrame) -> None:
    node = CreateTable(
        user_id="user-1",
        project_id="proj-1",
        task_id="task-1",
        node_id=f"create_{table_name}",
        connection=connection,
        table_name=table_name,
        dataframe_metadata=get_df_metadata(df),
        on_exists="recreate",
    )
    await node.process()


def _get_write_to_db_v3(
    connection,
    df,
    table_name="test_columns_pipeline",
    write_mode="truncate",
    node_id="write_table",
):
    return {
        node_id: NodeData(
            name="WriteDataFrameToDBV3",
            inputs={
                "connection": NodeInputConstantValue(value=connection),
                "table_name": NodeInputConstantValue(value=table_name),
                "df": NodeInputConstantValue(value=df),
                "write_mode": NodeInputConstantValue(value=write_mode),
            },
        )
    }


def _get_read_query_v3(
    connection,
    sql_code="SELECT * FROM test_columns_pipeline",
    node_id="read_query",
    partition_col=None,
    partition_grouping=None,
):
    inputs = {
        "connection": NodeInputConstantValue(value=connection),
        "sql_code": NodeInputConstantValue(value=sql_code),
    }
    if partition_col is not None:
        inputs["partition_col"] = NodeInputConstantValue(value=partition_col)
    if partition_grouping is not None:
        inputs["partition_grouping"] = NodeInputConstantValue(value=partition_grouping)

    return {
        node_id: NodeData(
            name="ReadQueryFromDBV3",
            inputs=inputs,
        )
    }


async def _run_pipeline_and_get_output(
    pipeline: dict[str, NodeData],
    target_nodes: list[str],
    output_node_id: str,
) -> pd.DataFrame:
    processor = PipelineProcessor(task=_build_task(pipeline, target_nodes))
    await asyncio.wait_for(processor.process(), timeout=PIPELINE_PROCESS_TIMEOUT_SEC)
    return _get_node_df(processor, output_node_id)


async def test_simple_pipeline_with_read_table(clickhouse_http_test_engine, simple_df):
    df_copy = simple_df.copy()
    df = dd.from_pandas(simple_df)
    await _ensure_table(clickhouse_http_test_engine, "test_columns_pipeline", df)

    pipeline = {
        **_get_write_to_db_v3(connection=clickhouse_http_test_engine, df=df),
        "read_table": NodeData(
            name="ReadTableFromDBV3",
            inputs={
                "connection": NodeInputConstantValue(value=clickhouse_http_test_engine),
                "table_name": NodeInputConstantValue(value="test_columns_pipeline"),
                "columns": NodeInputConstantValue(value=list(simple_df.columns)),
                "partition_col": NodeInputConstantValue(value="id"),
            },
        ),
    }

    res_df = await _run_pipeline_and_get_output(
        pipeline=pipeline,
        target_nodes=["write_table", "read_table"],
        output_node_id="read_table",
    )

    assert_frame_equal(
        df_copy.reset_index(drop=True),
        res_df.reset_index(drop=True),
        check_dtype=False,
        check_exact=False
    )

    with clickhouse_http_test_engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS test_columns_pipeline"))


async def test_simple_pipeline_with_read_query(clickhouse_http_test_engine, simple_df):
    df_copy = simple_df.copy()
    df = dd.from_pandas(simple_df)
    await _ensure_table(clickhouse_http_test_engine, "test_columns_pipeline", df)

    pipeline = {
        **_get_write_to_db_v3(connection=clickhouse_http_test_engine, df=df),
        **_get_read_query_v3(connection=clickhouse_http_test_engine, partition_col="id"),
    }

    res_df = await _run_pipeline_and_get_output(
        pipeline=pipeline,
        target_nodes=["write_table", "read_query"],
        output_node_id="read_query",
    )

    assert_frame_equal(
        df_copy.reset_index(drop=True),
        res_df.reset_index(drop=True),
        check_dtype=False,
        check_exact=False
    )

    with clickhouse_http_test_engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS test_columns_pipeline"))


async def test_pipeline_with_select_and_filter(clickhouse_http_test_engine, simple_df):
    df = simple_df
    df = df[['name', 'age']]
    df = df[df['name'] == 'Alice']
    df_copy = df.copy()
    df = dd.from_pandas(df)
    await _ensure_table(clickhouse_http_test_engine, "test_columns_pipeline", df)

    pipeline = {
        **_get_write_to_db_v3(connection=clickhouse_http_test_engine, df=df),
        **_get_read_query_v3(
            connection=clickhouse_http_test_engine,
            partition_col="name",
            partition_grouping={"mode": "as_is"},
        ),
        **get_select_columns(link_to_df='read_query', columns=['name', 'age']),
        **get_filter(link_to_df='select', conditions=build_condition("name", "==", "Alice")),
    }

    res_df = await _run_pipeline_and_get_output(
        pipeline=pipeline,
        target_nodes=["write_table", "read_query", "select", "filter"],
        output_node_id="filter",
    )

    assert_frame_equal(
        df_copy.reset_index(drop=True),
        res_df.reset_index(drop=True),
        check_dtype=False,
        check_exact=False
    )

    with clickhouse_http_test_engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS test_columns_pipeline"))


async def test_pipeline_with_drop_exec_join(clickhouse_http_test_engine, simple_df, simple_df_two):
    df = simple_df
    df2 = simple_df_two
    df_copy = df.drop(labels=['unused_column'], axis=1)
    df_copy: pd.DataFrame = df_copy[df_copy['age'] > 30]
    df_copy = pd.merge(df_copy, df2, how='left', left_on='name', right_on='name')
    df_copy = df_copy.copy()
    df = dd.from_pandas(df)
    df2 = dd.from_pandas(df2)
    await _ensure_table(clickhouse_http_test_engine, "test_columns_pipeline", df)
    await _ensure_table(clickhouse_http_test_engine, "test_columns_pipeline_join", df2)

    pipeline = {
        **_get_write_to_db_v3(connection=clickhouse_http_test_engine, df=df),
        **_get_write_to_db_v3(
            node_id='write_table_2',
            connection=clickhouse_http_test_engine,
            df=df2,
            table_name='test_columns_pipeline_join',
        ),
        **_get_read_query_v3(
            connection=clickhouse_http_test_engine,
            partition_col="id",
            partition_grouping={"mode": "hash", "buckets": 4},
        ),
        **_get_read_query_v3(
            node_id='read_query_2',
            connection=clickhouse_http_test_engine,
            sql_code="SELECT * FROM test_columns_pipeline_join",
            partition_col="name",
            partition_grouping={"mode": "as_is"},
        ),
        **get_drop_columns(link_to_df='read_query', columns=['unused_column']),
        **get_exec_code(link_to_df='drop', code="df_out=df_in[df_in['age'] > 30]"),
        **get_join(left_link_to_df='exec_code', right_link_to_df='read_query_2', left_on='name', right_on='name'),
    }

    res_df = await _run_pipeline_and_get_output(
        pipeline=pipeline,
        target_nodes=[
            "write_table",
            "write_table_2",
            "read_query",
            "read_query_2",
            "drop",
            "exec_code",
            "join",
        ],
        output_node_id="join",
    )

    assert_frame_equal(
        df_copy.sort_values("id").reset_index(drop=True),
        res_df.reset_index(drop=True).sort_values("id").reset_index(drop=True),
        check_dtype=False,
        check_exact=False
    )

    with clickhouse_http_test_engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS test_columns_pipeline"))
        conn.execute(text("DROP TABLE IF EXISTS test_columns_pipeline_join"))


async def test_simple_pipeline_with_s3_save_load_excel(get_mock_s3_db_connection, simple_df):
    df_copy = simple_df.copy()
    df = dd.from_pandas(simple_df)
    pipeline = {
        **get_save_excel(connection=get_mock_s3_db_connection, df=df),
        **get_load_excel(connection=get_mock_s3_db_connection, path="testing_folder/testing_file.xlsx"),
    }

    res_df = await _run_pipeline_and_get_output(
        pipeline=pipeline,
        target_nodes=["save_excel", "load_excel"],
        output_node_id="load_excel",
    )

    assert_frame_equal(
        df_copy.reset_index(drop=True),
        res_df.reset_index(drop=True),
        check_dtype=False,
        check_exact=False
    )


async def test_simple_pipeline_with_s3_save_load_csv(get_mock_s3_db_connection, simple_df):
    df_copy = simple_df.copy()
    df = dd.from_pandas(simple_df)
    pipeline = {
        "write_csv": NodeData(
            name="SaveCSV",
            inputs={
                "connection": NodeInputConstantValue(value=get_mock_s3_db_connection),
                "df": NodeInputConstantValue(value=df),
                "path": NodeInputConstantValue(value="testing_folder/testing_file.csv"),
            },
        ),
        "load_csv": NodeData(
            name="LoadCSV",
            inputs={
                "connection": NodeInputConstantValue(value=get_mock_s3_db_connection),
                "path": NodeInputConstantValue(value="testing_folder/testing_file.csv"),
            },
        ),
    }

    res_df = await _run_pipeline_and_get_output(
        pipeline=pipeline,
        target_nodes=["write_csv", "load_csv"],
        output_node_id="load_csv",
    )

    assert_frame_equal(
        df_copy.reset_index(drop=True),
        res_df.reset_index(drop=True),
        check_dtype=False,
        check_exact=False
    )


async def test_pipeline_s3_load_csv_db_filters_join(
    clickhouse_http_test_engine,
    get_mock_s3_db_connection,
    simple_df,
    simple_df_two,
):
    df = simple_df
    df2 = simple_df_two
    df_copy = df[df['age'] > 30]
    df_copy = pd.merge(df_copy, df2, how='left', left_on='name', right_on='name')
    df_copy = df_copy[df_copy['surname'] == "Johnson"]
    df_copy = df_copy.copy()
    df = dd.from_pandas(df)
    df2 = dd.from_pandas(df2)
    await _ensure_table(clickhouse_http_test_engine, "test_columns_pipeline_join", df2)
    pipeline = {
        **get_save_excel(connection=get_mock_s3_db_connection, df=df),
        **get_load_excel(connection=get_mock_s3_db_connection, path="testing_folder/testing_file.xlsx"),
        **_get_write_to_db_v3(
            node_id='write_table_2',
            connection=clickhouse_http_test_engine,
            df=df2,
            table_name='test_columns_pipeline_join',
        ),
        **_get_read_query_v3(
            node_id='read_query_2',
            connection=clickhouse_http_test_engine,
            sql_code="SELECT * FROM test_columns_pipeline_join",
            partition_col="name",
            partition_grouping={"mode": "as_is"},
        ),
        **get_filter(link_to_df='load_excel', conditions=build_condition("age", ">", "30")),
        **get_join(left_link_to_df='filter', right_link_to_df='read_query_2', left_on='name', right_on='name'),
        **get_filter(
            link_to_df="join",
            conditions=build_condition("surname", "==", "Johnson"),
            node_id="filter_after_join",
        ),
    }

    res_df = await _run_pipeline_and_get_output(
        pipeline=pipeline,
        target_nodes=[
            "save_excel",
            "load_excel",
            "write_table_2",
            "read_query_2",
            "filter",
            "join",
            "filter_after_join",
        ],
        output_node_id="filter_after_join",
    )

    assert_frame_equal(
        df_copy.reset_index(drop=True),
        res_df.reset_index(drop=True),
        check_dtype=False,
        check_exact=False
    )

    with clickhouse_http_test_engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS test_columns_pipeline_join"))
