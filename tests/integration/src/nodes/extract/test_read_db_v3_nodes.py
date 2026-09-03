from __future__ import annotations

from datetime import datetime, timedelta

import sqlalchemy as sa
from dask import dataframe as dd
from sqlalchemy import text

from src.nodes.extract.read_query_from_db_v3 import ReadQueryFromDBV3
from src.nodes.extract.read_table_from_db_v3 import ReadTableFromDBV3

import config


def _seed(engine: sa.Engine, rows: int = 80) -> None:
    payload = []
    base_ts = datetime(2026, 1, 1, 0, 0, 0)
    groups = ["a", "b", "c", "d"]
    for idx in range(1, rows + 1):
        payload.append(
            {
                "id": idx,
                "category": groups[idx % len(groups)],
                "created_at": base_ts + timedelta(minutes=idx),
                "value": float(idx) * 1.1,
                "is_active": None if idx % 7 == 0 else (idx % 2 == 0),
            }
        )

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS read_v3_nodes_test"))
        conn.execute(
            text(
                """
                CREATE TABLE read_v3_nodes_test (
                    id INTEGER PRIMARY KEY,
                    category TEXT,
                    created_at DATETIME,
                    value REAL,
                    is_active BOOLEAN
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO read_v3_nodes_test (id, category, created_at, value, is_active)
                VALUES (:id, :category, :created_at, :value, :is_active)
                """
            ),
            payload,
        )


def _seed_large_payload(engine: sa.Engine, rows: int = 500, payload_size: int = 5_000) -> None:
    payload = [
        {
            "id": idx,
            "payload": f"{idx:04d}-" + ("x" * payload_size),
        }
        for idx in range(1, rows + 1)
    ]
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS read_v3_nodes_auto_test"))
        conn.execute(
            text(
                """
                CREATE TABLE read_v3_nodes_auto_test (
                    id INTEGER PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO read_v3_nodes_auto_test (id, payload)
                VALUES (:id, :payload)
                """
            ),
            payload,
        )


def test_read_table_from_db_v3_node_supports_limit(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'node_table_v3.sqlite'}")
    _seed(engine)

    node = ReadTableFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=engine,
        table_name="read_v3_nodes_test",
        schema_name=None,
        columns=["id", "category", "value"],
        partition_col="id",
        npartitions=5,
        limit=13,
    )

    node.process()

    assert isinstance(node.output, dd.DataFrame)
    assert node.output.known_divisions is True

    result = node.output.compute().reset_index(drop=True).sort_values("id").reset_index(drop=True)
    assert len(result) == 13
    assert result["id"].tolist() == list(range(1, 14))


def test_read_query_from_db_v3_node_supports_limit(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'node_query_v3.sqlite'}")
    _seed(engine)

    node = ReadQueryFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=engine,
        sql_code="SELECT id, category, created_at, value FROM read_v3_nodes_test",
        partition_col="id",
        npartitions=4,
        limit=15,
    )

    node.process()

    assert isinstance(node.output, dd.DataFrame)
    assert node.output.known_divisions is True

    result = node.output.compute().reset_index(drop=True).sort_values("id").reset_index(drop=True)
    assert len(result) == 15
    assert result["id"].tolist() == list(range(1, 16))


def test_read_table_from_db_v3_node_supports_partition_grouping(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'node_table_v3_grouping.sqlite'}")
    _seed(engine)

    node = ReadTableFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=engine,
        table_name="read_v3_nodes_test",
        schema_name=None,
        columns=["id", "category", "is_active"],
        partition_col="is_active",
        partition_grouping={"mode": "as_is"},
        npartitions=3,
    )

    node.process()

    assert isinstance(node.output, dd.DataFrame)
    assert node.output.known_divisions is True

    result = node.output.compute().reset_index(drop=True).sort_values("id").reset_index(drop=True)
    assert len(result) == 80
    assert result["id"].tolist() == list(range(1, 81))


def test_read_query_from_db_v3_node_supports_partition_grouping(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'node_query_v3_grouping.sqlite'}")
    _seed(engine)

    node = ReadQueryFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=engine,
        sql_code="SELECT id, category, created_at, value FROM read_v3_nodes_test",
        partition_col="category",
        partition_grouping={"mode": "prefix", "length": 1},
        npartitions=4,
    )

    node.process()

    assert isinstance(node.output, dd.DataFrame)
    assert node.output.known_divisions is True

    result = node.output.compute().reset_index(drop=True).sort_values("id").reset_index(drop=True)
    assert len(result) == 80
    assert result["id"].tolist() == list(range(1, 81))


def test_read_table_from_db_v3_node_auto_npartitions_is_memory_aware(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config.DASK_PARTITIONING, "TARGET_PARTITION_MEM_MB", 1)
    monkeypatch.setattr(config.DASK_PARTITIONING, "OVERHEAD_COEF", 1.0)
    monkeypatch.setattr(config.DASK_PARTITIONING, "MIN_ROWS_PER_PART", 50)

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'node_table_v3_auto.sqlite'}")
    _seed_large_payload(engine)

    node = ReadTableFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=engine,
        table_name="read_v3_nodes_auto_test",
        schema_name=None,
        columns=["id", "payload"],
        partition_col="id",
        npartitions=None,
    )

    node.process()

    assert isinstance(node.output, dd.DataFrame)
    assert node.output.known_divisions is True
    assert node.output.npartitions > 1
    result = node.output.compute().reset_index(drop=True).sort_values("id").reset_index(drop=True)
    assert len(result) == 500
    assert result["id"].tolist() == list(range(1, 501))


def test_read_query_from_db_v3_node_auto_npartitions_is_memory_aware(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config.DASK_PARTITIONING, "TARGET_PARTITION_MEM_MB", 1)
    monkeypatch.setattr(config.DASK_PARTITIONING, "OVERHEAD_COEF", 1.0)
    monkeypatch.setattr(config.DASK_PARTITIONING, "MIN_ROWS_PER_PART", 50)

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'node_query_v3_auto.sqlite'}")
    _seed_large_payload(engine)

    node = ReadQueryFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=engine,
        sql_code="SELECT id, payload FROM read_v3_nodes_auto_test",
        partition_col="id",
        npartitions=None,
    )

    node.process()

    assert isinstance(node.output, dd.DataFrame)
    assert node.output.known_divisions is True
    assert node.output.npartitions > 1
    result = node.output.compute().reset_index(drop=True).sort_values("id").reset_index(drop=True)
    assert len(result) == 500
    assert result["id"].tolist() == list(range(1, 501))
