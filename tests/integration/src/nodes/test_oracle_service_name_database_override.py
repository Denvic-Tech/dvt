from __future__ import annotations

from uuid import uuid4

import dask.dataframe as dd
import pandas as pd
import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from core.types import Column, DataFrameMetadata, DataType
from src.nodes.extract.read_table_from_db_v3 import ReadTableFromDBV3
from src.nodes.extract.read_variables_from_db import ReadVariablesFromDB
from src.nodes.tool.create_table import CreateTable
from src.nodes.write.write_df_to_db_v3 import WriteDataFrameToDBV3
from src.schemas.internal import ProjectSettings

pytestmark = pytest.mark.docker_required


def _oracle_service_name_engine(engine: sa.Engine) -> sa.Engine:
    service_name = engine.url.query.get("service_name") or engine.url.database
    assert service_name
    query = dict(engine.url.query)
    query["service_name"] = service_name
    return sa.create_engine(engine.url.set(database=None, query=query))


def _table_name(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}".lower()[:30]


def _drop_table(engine: sa.Engine, table_name: str) -> None:
    try:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE {table_name}"))
    except DatabaseError:
        pass


def _seed_table(engine: sa.Engine, table_name: str) -> None:
    _drop_table(engine, table_name)
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE {table_name} (
                    id NUMBER(10) PRIMARY KEY,
                    value VARCHAR2(50),
                    amount NUMBER(10)
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                INSERT INTO {table_name} (id, value, amount)
                VALUES (:id, :value, :amount)
                """
            ),
            [
                {"id": 1, "value": "first", "amount": 10},
                {"id": 2, "value": "second", "amount": 20},
            ],
        )


def test_read_table_from_db_v3_keeps_oracle_service_name_url_without_database_path(
        oracle_test_engine,
) -> None:
    engine = _oracle_service_name_engine(oracle_test_engine)
    table_name = _table_name("RTV3")
    _seed_table(engine, table_name)

    try:
        node = ReadTableFromDBV3(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-read-table-v3-oracle-service",
            connection=engine,
            database_name="SHOULD_NOT_BECOME_URL_DATABASE",
            schema_name=None,
            table_name=table_name,
            columns=["id", "value", "amount"],
            partition_col="id",
            npartitions=1,
        )

        node.process()

        result = node.output.compute().reset_index(drop=True).sort_values("id").reset_index(drop=True)
        assert result["id"].tolist() == [1, 2]
        assert result["value"].tolist() == ["first", "second"]
    finally:
        _drop_table(engine, table_name)
        engine.dispose()


@pytest.mark.asyncio
async def test_write_dataframe_to_db_v3_keeps_oracle_service_name_url_without_database_path(
        oracle_test_engine,
) -> None:
    engine = _oracle_service_name_engine(oracle_test_engine)
    table_name = _table_name("WTV3")
    _seed_table(engine, table_name)

    try:
        node = WriteDataFrameToDBV3(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-write-v3-oracle-service",
            connection=engine,
            database_name="SHOULD_NOT_BECOME_URL_DATABASE",
            schema_name=None,
            table_name=table_name,
            df=dd.from_pandas(
                pd.DataFrame(
                    {
                        "id": [3],
                        "value": ["third"],
                        "amount": [30],
                    }
                ),
                npartitions=1,
            ),
            write_mode="append",
            project_settings=ProjectSettings(store_enabled=False, ttl_time=0, workers_count=1),
        )

        await node.process()

        with engine.begin() as conn:
            rows = conn.execute(
                text(f"SELECT id, value, amount FROM {table_name} ORDER BY id")
            ).fetchall()
        assert rows == [(1, "first", 10), (2, "second", 20), (3, "third", 30)]
    finally:
        _drop_table(engine, table_name)
        engine.dispose()


@pytest.mark.asyncio
async def test_create_table_keeps_oracle_service_name_url_without_database_path(
        oracle_test_engine,
) -> None:
    engine = _oracle_service_name_engine(oracle_test_engine)
    table_name = _table_name("CTBL")
    _drop_table(engine, table_name)

    try:
        node = CreateTable(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-create-table-oracle-service",
            connection=engine,
            database_name="SHOULD_NOT_BECOME_URL_DATABASE",
            schema_name=None,
            table_name=table_name,
            dataframe_metadata=DataFrameMetadata(
                columns=[
                    Column(name="id", dtype=DataType.INT, nullable=False, index=True),
                    Column(name="value", dtype=DataType.STRING, nullable=True, index=False),
                ]
            ),
            on_exists="error",
        )

        await node.process()

        with engine.begin() as conn:
            exists = conn.execute(
                text("SELECT COUNT(*) FROM USER_TABLES WHERE TABLE_NAME = :table_name"),
                {"table_name": table_name.upper()},
            ).scalar_one()
        assert exists == 1
    finally:
        _drop_table(engine, table_name)
        engine.dispose()


def test_read_variables_from_db_keeps_oracle_service_name_url_without_database_path(
        oracle_test_engine,
) -> None:
    engine = _oracle_service_name_engine(oracle_test_engine)
    table_name = _table_name("RVAR")
    _seed_table(engine, table_name)

    try:
        node = ReadVariablesFromDB(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-read-vars-oracle-service",
            connection=engine,
            mode="manual",
            manual_variables={
                "max_amount": {
                    "database_name": "SHOULD_NOT_BECOME_URL_DATABASE",
                    "schema_name": None,
                    "table_name": table_name,
                    "column_name": "amount",
                    "aggregation": "max",
                }
            },
        )

        node.process()

        assert node.output_variables["max_amount"].value == 20
    finally:
        _drop_table(engine, table_name)
        engine.dispose()
