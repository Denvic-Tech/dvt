from services.gateway.routes.internal.ai_mcp import graph


def _constant(value):
    return {"__dvt_type": "const", "value": value}


def test_read_table_policy_requires_partition_and_explicit_columns() -> None:
    errors = graph._read_table_mcp_configuration_errors(
        node_id="read-node",
        inputs={
            "partition_col": _constant(None),
            "columns": _constant(None),
        },
    )

    assert {(error["input"], error["code"]) for error in errors} == {
        ("partition_col", "REQUIRED_INPUT_MISSING"),
        ("columns", "REQUIRED_INPUT_MISSING"),
    }


def test_read_table_policy_accepts_raw_partition_and_all_catalog_columns() -> None:
    errors = graph._read_table_mcp_configuration_errors(
        node_id="read-node",
        inputs={
            "partition_col": _constant("Наименование товара"),
            "columns": _constant(["Наименование товара", "Номер кассы"]),
        },
    )

    assert errors == []


def test_read_table_policy_rejects_sql_quoted_partition_column() -> None:
    errors = graph._read_table_mcp_configuration_errors(
        node_id="read-node",
        inputs={
            "partition_col": _constant("`Наименование товара`"),
            "columns": _constant(["Наименование товара"]),
        },
    )

    assert errors == [
        {
            "code": "INVALID_CONSTANT",
            "node_id": "read-node",
            "input": "partition_col",
            "message": "Use the raw catalog column name without SQL quotes or backticks.",
        }
    ]
