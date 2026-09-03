import asyncio

import pytest
import sqlalchemy as sa
from sqlalchemy import text

import src.nodes.extract.read_variables_from_db as read_variables_module
from src.node_dsl import IO, NodeValidationError
from src.nodes.extract.read_variables_from_db import ReadVariablesFromDB


def _build_engine(tmp_path, filename: str = "read_variables_from_db.sqlite") -> sa.Engine:
    engine = sa.create_engine(f"sqlite:///{tmp_path / filename}")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS orders"))
        conn.execute(text("DROP TABLE IF EXISTS customers"))
        conn.execute(
            text(
                """
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY,
                    customer_id INTEGER NOT NULL,
                    total_amount REAL,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE customers (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    tags_json TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO orders (id, customer_id, total_amount, created_at)
                VALUES
                    (1, 10, 120.5, '2026-01-01 10:00:00'),
                    (2, 11, 80.0, '2026-01-02 10:00:00'),
                    (3, 10, 150.0, '2026-01-03 10:00:00')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO customers (id, name, created_at, tags_json)
                VALUES
                    (10, 'Alice', '2026-01-01 09:00:00', '[1, 2]'),
                    (11, 'Bob', '2026-01-02 09:00:00', '[3, 4]')
                """
            )
        )
    return engine


def _build_node(engine: sa.Engine, **kwargs) -> ReadVariablesFromDB:
    return ReadVariablesFromDB(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=engine,
        **kwargs,
    )


def _extract_target_dtype_enum(schema: dict) -> list[str]:
    return next(option["enum"] for option in schema["anyOf"] if "enum" in option)


def test_read_variables_from_db_manual_mode_reads_variables(tmp_path) -> None:
    engine = _build_engine(tmp_path)
    node = _build_node(
        engine,
        mode="manual",
        manual_variables={
            "orders_count": {
                "table_name": "orders",
                "column_name": "id",
                "aggregation": "count",
            },
            "latest_order_id": {
                "table_name": "orders",
                "column_name": "id",
                "aggregation": "last",
                "order_by_column": "created_at",
            },
            "first_customer_name": {
                "table_name": "customers",
                "column_name": "name",
                "aggregation": "first",
                "order_by_column": "created_at",
            },
        },
    )

    node.process()

    assert node.output_variables["orders_count"].value == 3
    assert node.output_variables["orders_count"].type == "INT"
    assert node.output_variables["latest_order_id"].value == 3
    assert node.output_variables["latest_order_id"].type == "INT"
    assert node.output_variables["first_customer_name"].value == "Alice"
    assert node.output_variables["first_customer_name"].type == "STRING"


def test_read_variables_from_db_manual_mode_applies_target_dtype_override(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_manual_target_dtype.sqlite")
    node = _build_node(
        engine,
        mode="manual",
        manual_variables={
            "orders_count": {
                "table_name": "orders",
                "column_name": "id",
                "aggregation": "count",
                "target_dtype": "STRING",
            }
        },
    )

    node.process()

    assert node.output_variables["orders_count"].value == "3"
    assert node.output_variables["orders_count"].type == "STRING"


def test_read_variables_from_db_manual_mode_reads_list_variable(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_manual_list.sqlite")
    node = _build_node(
        engine,
        mode="manual",
        manual_variables={
            "customer_tags": {
                "table_name": "customers",
                "column_name": "tags_json",
                "aggregation": "first",
                "order_by_column": "created_at",
                "is_list_type": True,
                "target_dtype": "INT",
            }
        },
    )

    node.process()

    assert node.output_variables["customer_tags"].value == [1, 2]
    assert node.output_variables["customer_tags"].type == "INT"
    assert node.output_variables["customer_tags"].is_list_type is True


def test_read_variables_from_db_process_metadata_executes_queries(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_metadata.sqlite")
    node = _build_node(
        engine,
        mode="manual",
        manual_variables={
            "orders_total": {
                "table_name": "orders",
                "column_name": "total_amount",
                "aggregation": "sum",
            }
        },
    )

    node.process_metadata()

    assert node.output_variables["orders_total"].value == pytest.approx(350.5)
    assert node.output_variables["orders_total"].type == "FLOAT"


def test_read_variables_from_db_manual_mode_validate_skips_empty_sql_code(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_manual_validate.sqlite")
    node = _build_node(
        engine,
        mode="manual",
        manual_variables={
            "orders_count": {
                "table_name": "orders",
                "column_name": "id",
                "aggregation": "count",
            }
        },
    )

    asyncio.run(node.validate())


def test_read_variables_from_db_sql_mode_validate_requires_sql_code(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_sql_validate.sqlite")
    node = _build_node(
        engine,
        mode="sql",
        sql_code="   ",
    )

    with pytest.raises(NodeValidationError, match=r"`sql_query` must be a non-empty string"):
        asyncio.run(node.validate())


def test_read_variables_from_db_sql_mode_maps_columns_to_variables(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_sql.sqlite")
    node = _build_node(
        engine,
        mode="sql",
        sql_code="""
            SELECT
                COUNT(*) AS orders_count,
                MAX(total_amount) AS max_total
            FROM orders
        """,
    )

    node.process()

    assert node.output_variables["orders_count"].value == 3
    assert node.output_variables["orders_count"].type == "INT"
    assert node.output_variables["max_total"].value == 150.0
    assert node.output_variables["max_total"].type == "FLOAT"


def test_read_variables_from_db_sql_mode_prefers_described_boolean_type_over_string_value(
    monkeypatch,
) -> None:
    node = _build_node(
        sa.create_engine("sqlite:///:memory:"),
        mode="sql",
        sql_code="SELECT 'true' AS enabled",
    )
    monkeypatch.setattr(
        ReadVariablesFromDB,
        "_execute_preview_query",
        staticmethod(lambda **_kwargs: (["enabled"], [("true",)])),
    )
    monkeypatch.setattr(
        ReadVariablesFromDB,
        "_get_query_column_types",
        staticmethod(lambda **_kwargs: {"enabled": IO.BOOLEAN}),
    )

    node.process()

    assert node.output_variables["enabled"].type == "BOOLEAN"


def test_read_variables_from_db_sql_mode_prefers_described_int_type_over_string_value(
    monkeypatch,
) -> None:
    node = _build_node(
        sa.create_engine("sqlite:///:memory:"),
        mode="sql",
        sql_code="SELECT '1' AS sample_int",
    )
    monkeypatch.setattr(
        ReadVariablesFromDB,
        "_execute_preview_query",
        staticmethod(lambda **_kwargs: (["sample_int"], [("1",)])),
    )
    monkeypatch.setattr(
        ReadVariablesFromDB,
        "_get_query_column_types",
        staticmethod(lambda **_kwargs: {"sample_int": IO.INT}),
    )

    node.process()

    assert node.output_variables["sample_int"].type == "INT"


def test_read_variables_from_db_get_query_column_types_matches_normalized_described_names(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        read_variables_module,
        "describe_query_columns",
        lambda *_args, **_kwargs: [("`ENABLED`", "Bool"), (" SAMPLE_INT ", "Int32")],
    )

    column_types = ReadVariablesFromDB._get_query_column_types(
        engine=sa.create_engine("sqlite:///:memory:"),
        raw_query="SELECT 1",
        column_names=["enabled", "sample_int"],
    )

    assert column_types == {"enabled": IO.BOOLEAN, "sample_int": IO.INT}


def test_read_variables_from_db_sql_mode_matches_overrides_by_normalized_column_name(
    monkeypatch,
) -> None:
    node = _build_node(
        sa.create_engine("sqlite:///:memory:"),
        mode="sql",
        sql_code="SELECT 'ignored' AS enabled",
        sql_variables={
            "enabled": {"default": "false", "target_dtype": "BOOLEAN"},
        },
    )
    monkeypatch.setattr(
        ReadVariablesFromDB,
        "_execute_preview_query",
        staticmethod(lambda **_kwargs: ([" ENABLED "], [])),
    )
    monkeypatch.setattr(
        ReadVariablesFromDB,
        "_get_query_column_types",
        staticmethod(lambda **_kwargs: {" ENABLED ": IO.BOOLEAN}),
    )

    node.process()

    assert node.output_variables[" ENABLED "].value is False
    assert node.output_variables[" ENABLED "].type == "BOOLEAN"


def test_read_variables_from_db_sql_mode_requires_single_row(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_sql_rows.sqlite")
    node = _build_node(
        engine,
        mode="sql",
        sql_code="SELECT id FROM orders ORDER BY id",
    )

    with pytest.raises(ValueError, match="more than 1 row"):
        node.process()


def test_read_variables_from_db_rejects_null_values_without_policy(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_nulls.sqlite")
    with engine.begin() as conn:
        conn.execute(text("UPDATE orders SET total_amount = NULL"))

    node = _build_node(
        engine,
        mode="manual",
        manual_variables={
            "max_total": {
                "table_name": "orders",
                "column_name": "total_amount",
                "aggregation": "max",
            }
        },
    )

    with pytest.raises(ValueError, match=r"default|nullable=true"):
        node.process()


def test_read_variables_from_db_manual_mode_uses_default_for_null_aggregate(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_manual_default.sqlite")
    with engine.begin() as conn:
        conn.execute(text("UPDATE orders SET total_amount = NULL"))

    node = _build_node(
        engine,
        mode="manual",
        manual_variables={
            "max_total": {
                "table_name": "orders",
                "column_name": "total_amount",
                "aggregation": "max",
                "default": 0.0,
            }
        },
    )

    node.process()

    assert node.output_variables["max_total"].value == 0.0
    assert node.output_variables["max_total"].type == "FLOAT"


def test_read_variables_from_db_manual_mode_applies_target_dtype_to_default(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_manual_target_default.sqlite")
    with engine.begin() as conn:
        conn.execute(text("UPDATE orders SET total_amount = NULL"))

    node = _build_node(
        engine,
        mode="manual",
        manual_variables={
            "max_total": {
                "table_name": "orders",
                "column_name": "total_amount",
                "aggregation": "max",
                "default": "0",
                "target_dtype": "INT",
            }
        },
    )

    node.process()

    assert node.output_variables["max_total"].value == 0
    assert node.output_variables["max_total"].type == "INT"


def test_read_variables_from_db_manual_mode_keeps_none_for_nullable_first_on_empty_table(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_manual_nullable.sqlite")
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM customers"))

    node = _build_node(
        engine,
        mode="manual",
        manual_variables={
            "first_customer_name": {
                "table_name": "customers",
                "column_name": "name",
                "aggregation": "first",
                "order_by_column": "created_at",
                "nullable": True,
            }
        },
    )

    node.process()

    assert node.output_variables["first_customer_name"].value is None
    assert node.output_variables["first_customer_name"].type == "STRING"


def test_read_variables_from_db_sql_mode_zero_rows_uses_column_overrides(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_sql_zero_rows.sqlite")
    node = _build_node(
        engine,
        mode="sql",
        sql_code="""
            SELECT
                id AS latest_order_id,
                total_amount AS latest_total
            FROM orders
            WHERE 1 = 0
        """,
        sql_variables={
            "latest_order_id": {"default": 0},
            "latest_total": {"nullable": True},
        },
    )

    node.process()

    assert node.output_variables["latest_order_id"].value == 0
    assert node.output_variables["latest_order_id"].type == "INT"
    assert node.output_variables["latest_total"].value is None


def test_read_variables_from_db_sql_mode_applies_target_dtype_overrides(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_sql_target_dtype.sqlite")
    node = _build_node(
        engine,
        mode="sql",
        sql_code="""
            SELECT
                COUNT(*) AS orders_count,
                MAX(total_amount) AS max_total
            FROM orders
        """,
        sql_variables={
            "orders_count": {"target_dtype": "STRING"},
            "max_total": {"target_dtype": "INT"},
        },
    )

    node.process()

    assert node.output_variables["orders_count"].value == "3"
    assert node.output_variables["orders_count"].type == "STRING"
    assert node.output_variables["max_total"].value == 150
    assert node.output_variables["max_total"].type == "INT"


def test_read_variables_from_db_sql_mode_reads_list_variable_and_infers_item_type(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_sql_list.sqlite")
    node = _build_node(
        engine,
        mode="sql",
        sql_code="SELECT '[1, 2, 3]' AS order_ids",
        sql_variables={
            "order_ids": {"is_list_type": True},
        },
    )

    node.process()

    assert node.output_variables["order_ids"].value == [1, 2, 3]
    assert node.output_variables["order_ids"].type == "INT"
    assert node.output_variables["order_ids"].is_list_type is True


def test_read_variables_from_db_sql_mode_rejects_empty_list_without_target_dtype(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_sql_empty_list.sqlite")
    node = _build_node(
        engine,
        mode="sql",
        sql_code="SELECT '[]' AS order_ids",
        sql_variables={
            "order_ids": {"is_list_type": True},
        },
    )

    with pytest.raises(ValueError, match=r"empty list|target_dtype"):
        node.process()


def test_read_variables_from_db_sql_mode_rejects_mixed_list_without_target_dtype(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_sql_mixed_list.sqlite")
    node = _build_node(
        engine,
        mode="sql",
        sql_code="""SELECT '[1, \"x\"]' AS order_ids""",
        sql_variables={
            "order_ids": {"is_list_type": True},
        },
    )

    with pytest.raises(ValueError, match=r"mixed list|target_dtype"):
        node.process()


def test_read_variables_from_db_sql_mode_applies_target_dtype_to_zero_row_overrides(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_sql_target_zero_rows.sqlite")
    node = _build_node(
        engine,
        mode="sql",
        sql_code="""
            SELECT
                id AS latest_order_id,
                total_amount AS latest_total
            FROM orders
            WHERE 1 = 0
        """,
        sql_variables={
            "latest_order_id": {"default": "0", "target_dtype": "INT"},
            "latest_total": {"nullable": True, "target_dtype": "FLOAT"},
        },
    )

    node.process()

    assert node.output_variables["latest_order_id"].value == 0
    assert node.output_variables["latest_order_id"].type == "INT"
    assert node.output_variables["latest_total"].value is None
    assert node.output_variables["latest_total"].type == "FLOAT"


def test_read_variables_from_db_sql_mode_rejects_unknown_overrides(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_sql_unknown_override.sqlite")
    node = _build_node(
        engine,
        mode="sql",
        sql_code="SELECT COUNT(*) AS orders_count FROM orders",
        sql_variables={"missing_column": {"default": 1}},
    )

    with pytest.raises(ValueError, match="missing_column"):
        node.process()


def test_read_variables_from_db_rejects_invalid_target_dtype(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_invalid_target_dtype.sqlite")
    node = _build_node(
        engine,
        mode="manual",
        manual_variables={
            "orders_count": {
                "table_name": "orders",
                "column_name": "id",
                "aggregation": "count",
                "target_dtype": "OBJECT",
            }
        },
    )

    with pytest.raises(NodeValidationError, match="target_dtype"):
        asyncio.run(node.validate())


def test_read_variables_from_db_rejects_uncoercible_target_dtype(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_uncoercible_target_dtype.sqlite")
    node = _build_node(
        engine,
        mode="manual",
        manual_variables={
            "first_customer_name": {
                "table_name": "customers",
                "column_name": "name",
                "aggregation": "first",
                "order_by_column": "created_at",
                "target_dtype": "INT",
            }
        },
    )

    with pytest.raises(ValueError, match="valid integer"):
        node.process()


def test_read_variables_from_db_requires_order_by_for_first_and_last(tmp_path) -> None:
    engine = _build_engine(tmp_path, filename="read_variables_validation.sqlite")
    node = _build_node(
        engine,
        mode="manual",
        manual_variables={
            "latest_order_id": {
                "table_name": "orders",
                "column_name": "id",
                "aggregation": "last",
            }
        },
    )

    with pytest.raises(NodeValidationError, match="order_by_column"):
        asyncio.run(node.validate())


def test_read_variables_from_db_exposes_manual_schema_for_future_ui() -> None:
    field_schema = ReadVariablesFromDB._input_field_instances["manual_variables"].schema

    assert field_schema is not None
    assert field_schema["type"] == "object"
    assert field_schema["additionalProperties"]["properties"]["table_name"]["type"] == "string"
    assert field_schema["additionalProperties"]["properties"]["column_name"]["type"] == "string"
    assert field_schema["additionalProperties"]["properties"]["nullable"]["default"] is False
    assert field_schema["additionalProperties"]["properties"]["is_list_type"]["default"] is False
    assert "default" in field_schema["additionalProperties"]["properties"]
    assert _extract_target_dtype_enum(
        field_schema["additionalProperties"]["properties"]["target_dtype"]
    ) == [
        "STRING",
        "BOOLEAN",
        "INT",
        "FLOAT",
        "DATETIME",
        "TIMEDELTA",
        "JSON",
    ]
    assert field_schema["additionalProperties"]["properties"]["aggregation"]["enum"] == [
        "min",
        "max",
        "count",
        "count_distinct",
        "sum",
        "avg",
        "first",
        "last",
    ]
    sql_field_schema = ReadVariablesFromDB._input_field_instances["sql_variables"].schema
    assert sql_field_schema is not None
    assert sql_field_schema["type"] == "object"
    assert sql_field_schema["additionalProperties"]["properties"]["nullable"]["default"] is False
    assert sql_field_schema["additionalProperties"]["properties"]["is_list_type"]["default"] is False
    assert "default" in sql_field_schema["additionalProperties"]["properties"]
    assert _extract_target_dtype_enum(
        sql_field_schema["additionalProperties"]["properties"]["target_dtype"]
    ) == [
        "STRING",
        "BOOLEAN",
        "INT",
        "FLOAT",
        "DATETIME",
        "TIMEDELTA",
        "JSON",
    ]
    assert (
        ReadVariablesFromDB.ADDITIONAL_SCHEMA["read_variables_from_db"]["sql_mode"][
            "must_return_at_most_one_row"
        ]
        is True
    )
    assert (
        ReadVariablesFromDB.ADDITIONAL_SCHEMA["read_variables_from_db"]["sql_mode"][
            "zero_rows_allowed_with_defaults_or_nullable"
        ]
        is True
    )
    assert (
        ReadVariablesFromDB.ADDITIONAL_SCHEMA["read_variables_from_db"]["manual_mode"][
            "target_dtype_override_supported"
        ]
        is True
    )
    assert (
        ReadVariablesFromDB.ADDITIONAL_SCHEMA["read_variables_from_db"]["manual_mode"][
            "list_type_supported"
        ]
        is True
    )
