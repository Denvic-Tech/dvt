import dask.dataframe as dd
import pandas as pd
import pytest

from src.modules.data_catalog import ColumnSchema, TableSchema
from src.node_dsl import NodeValidationError
from src.nodes.tool.schema_policy import SchemaPolicy


def _build_node(
    dataframe: dd.DataFrame,
    schema: TableSchema,
    policy: dict,
) -> SchemaPolicy:
    return SchemaPolicy(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="schema-policy-1",
        df=dataframe,
        schema=schema,
        policy=policy,
    )


def test_schema_policy_fills_missing_drops_extra_and_casts() -> None:
    dataframe = dd.from_pandas(
        pd.DataFrame(
            {
                "id": ["1", "2"],
                "amount": [1, 2],
                "extra": ["x", "y"],
            }
        ),
        npartitions=1,
    )
    schema = TableSchema(
        columns=(
            ColumnSchema(name="id", dtype="INTEGER"),
            ColumnSchema(name="amount", dtype="FLOAT"),
            ColumnSchema(name="country", dtype="VARCHAR"),
        )
    )
    node = _build_node(
        dataframe,
        schema,
        {
            "on_extra_columns": "drop",
            "columns": {
                "id": {"on_missing": "error", "on_type_mismatch": "cast"},
                "amount": {"on_missing": "error", "on_type_mismatch": "cast"},
                "country": {
                    "on_missing": "fill",
                    "fill_value": "RU",
                    "on_type_mismatch": "error",
                },
            },
        },
    )

    node.process()
    result = node.output.compute()

    assert list(result.columns) == ["id", "amount", "country"]
    assert result["id"].dtype == pd.Int64Dtype()
    assert result["amount"].dtype == "float64"
    assert result["country"].dtype == pd.StringDtype()
    assert result["country"].tolist() == ["RU", "RU"]


def test_schema_policy_requires_policy_for_every_schema_column() -> None:
    dataframe = dd.from_pandas(pd.DataFrame({"id": [1]}), npartitions=1)
    schema = TableSchema(
        columns=(ColumnSchema(name="id", dtype="INT"), ColumnSchema(name="name"))
    )
    node = _build_node(
        dataframe,
        schema,
        {"columns": {"id": {"on_missing": "error", "on_type_mismatch": "error"}}},
    )

    with pytest.raises(NodeValidationError, match="not configured"):
        node.process()


def test_schema_policy_errors_on_extra_columns() -> None:
    dataframe = dd.from_pandas(pd.DataFrame({"id": [1], "extra": [2]}), npartitions=1)
    schema = TableSchema(columns=(ColumnSchema(name="id", dtype="INT"),))
    node = _build_node(
        dataframe,
        schema,
        {
            "on_extra_columns": "error",
            "columns": {"id": {"on_missing": "error", "on_type_mismatch": "error"}},
        },
    )

    with pytest.raises(NodeValidationError, match="absent from Schema"):
        node.process()


def test_schema_policy_errors_on_dtype_mismatch_from_metadata() -> None:
    dataframe = dd.from_pandas(pd.DataFrame({"id": ["1"]}), npartitions=1)
    schema = TableSchema(columns=(ColumnSchema(name="id", dtype="INTEGER"),))
    node = _build_node(
        dataframe,
        schema,
        {
            "columns": {"id": {"on_missing": "error", "on_type_mismatch": "error"}},
        },
    )

    with pytest.raises(NodeValidationError, match="expected"):
        node.process()


def test_schema_policy_soft_cast_coerces_invalid_values_to_null() -> None:
    dataframe = dd.from_pandas(
        pd.DataFrame({"id": ["1", "bad", "3.5", None]}),
        npartitions=2,
    )
    schema = TableSchema(columns=(ColumnSchema(name="id", dtype="INT"),))
    node = _build_node(
        dataframe,
        schema,
        {
            "columns": {
                "id": {"on_missing": "error", "on_type_mismatch": "soft_cast"}
            }
        },
    )

    node.process()
    result = node.output.compute()

    assert result["id"].dtype == pd.Int64Dtype()
    assert result["id"].tolist()[0] == 1
    assert pd.isna(result["id"].tolist()[1])
    assert pd.isna(result["id"].tolist()[2])
    assert pd.isna(result["id"].tolist()[3])


def test_schema_policy_strict_cast_fails_on_invalid_data_at_compute() -> None:
    dataframe = dd.from_pandas(pd.DataFrame({"id": ["1", "bad"]}), npartitions=1)
    schema = TableSchema(columns=(ColumnSchema(name="id", dtype="INT"),))
    node = _build_node(
        dataframe,
        schema,
        {
            "columns": {"id": {"on_missing": "error", "on_type_mismatch": "cast"}}
        },
    )

    node.process()

    with pytest.raises(ValueError, match="failed to cast column 'id'"):
        node.output.compute()


def test_schema_policy_normalizes_sql_and_pandas_dtypes() -> None:
    dataframe = dd.from_pandas(pd.DataFrame({"id": pd.Series([1, 2], dtype="int64")}), npartitions=1)
    schema = TableSchema(columns=(ColumnSchema(name="id", dtype="BIGINT"),))
    node = _build_node(
        dataframe,
        schema,
        {
            "columns": {"id": {"on_missing": "error", "on_type_mismatch": "error"}}
        },
    )

    node.process()
    result = node.output.compute()

    assert result["id"].dtype == "int64"


def test_schema_policy_metadata_mode_builds_expected_meta_without_compute() -> None:
    dataframe = dd.from_pandas(pd.DataFrame({"id": ["1"]}), npartitions=1)
    schema = TableSchema(
        columns=(ColumnSchema(name="id", dtype="INT"), ColumnSchema(name="name", dtype="STRING"))
    )
    node = _build_node(
        dataframe,
        schema,
        {
            "columns": {
                "id": {"on_missing": "error", "on_type_mismatch": "soft_cast"},
                "name": {"on_missing": "fill", "fill_value": "unknown"},
            }
        },
    )

    node.process_metadata()

    assert list(node.output.columns) == ["id", "name"]
    assert node.output._meta["id"].dtype == pd.Int64Dtype()
    assert node.output._meta["name"].dtype == pd.StringDtype()