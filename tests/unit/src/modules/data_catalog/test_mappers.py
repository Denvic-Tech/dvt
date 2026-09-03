from decimal import Decimal

import dask
import dask.dataframe as dd
import pandas as pd
import pytest

from src.modules.data_catalog import (
    DataFrameSchemaMapping,
    build_table_schema_from_dataframe,
)
from src.modules.data_catalog.domain import InvalidColumnSchemaError, TableSchema
from src.modules.data_catalog.infra import DataFrameSchemaMappingError


def _dataframe(data: dict[str, list[object]]) -> dd.DataFrame:
    with dask.config.set({"dataframe.convert-string": False}):
        return dd.from_pandas(pd.DataFrame(data), npartitions=1)


def test_build_table_schema_maps_all_supported_fields_and_metadata() -> None:
    dataframe = _dataframe(
        {
            "name": ["amount", "customer_id"],
            "dtype": [" decimal ", " UUID "],
            "description": [None, " Customer identifier "],
            "nullable": ["false", 1],
            "default": [pd.NA, Decimal("0")],
            "position": ["2", 1.0],
            "primary_key": [0, True],
            "unique": ["TRUE", "false"],
            "precision": [10.0, None],
            "scale": ["2", None],
            "length": [None, 36],
            "format": [None, " UUID "],
            "owner": [pd.NA, "core"],
        }
    )
    mapping = DataFrameSchemaMapping(
        column_names="name",
        column_dtypes="dtype",
        column_descriptions="description",
        column_nullable="nullable",
        column_defaults="default",
        column_order="position",
        column_primary_key="primary_key",
        column_unique="unique",
        column_precision="precision",
        column_scale="scale",
        column_length="length",
        column_format="format",
        metadata_columns=("owner",),
    )

    schema = build_table_schema_from_dataframe(dataframe=dataframe, mapping=mapping)

    assert [column.name for column in schema.columns] == ["customer_id", "amount"]
    customer_id, amount = schema.columns
    assert customer_id.dtype == "UUID"
    assert customer_id.description == "Customer identifier"
    assert customer_id.nullable is True
    assert customer_id.default == Decimal("0")
    assert customer_id.order == 1
    assert customer_id.primary_key is True
    assert customer_id.unique is False
    assert customer_id.length == 36
    assert customer_id.format == "UUID"
    assert customer_id.metadata == {"owner": "core"}
    assert amount.dtype == "decimal"
    assert amount.nullable is False
    assert amount.precision == 10
    assert amount.scale == 2
    assert amount.metadata == {"owner": None}


def test_build_table_schema_supports_minimal_and_empty_inputs() -> None:
    mapping = DataFrameSchemaMapping(column_names="name")

    minimal = build_table_schema_from_dataframe(
        dataframe=_dataframe({"name": ["id"]}), mapping=mapping
    )
    empty = build_table_schema_from_dataframe(dataframe=_dataframe({"name": []}), mapping=mapping)

    assert minimal == TableSchema(columns=(minimal.columns[0],))
    assert minimal.columns[0].name == "id"
    assert empty == TableSchema()


@pytest.mark.parametrize(
    ("data", "mapping"),
    [
        (
            {"name": ["id"], "nullable": ["yes"]},
            DataFrameSchemaMapping(column_names="name", column_nullable="nullable"),
        ),
        (
            {"name": ["id"], "position": [None]},
            DataFrameSchemaMapping(column_names="name", column_order="position"),
        ),
        (
            {"name": ["id"], "length": [1.5]},
            DataFrameSchemaMapping(column_names="name", column_length="length"),
        ),
    ],
)
def test_mapper_rejects_invalid_typed_values(
    data: dict[str, list[object]], mapping: DataFrameSchemaMapping
) -> None:
    with pytest.raises(DataFrameSchemaMappingError):
        build_table_schema_from_dataframe(dataframe=_dataframe(data), mapping=mapping)


def test_mapper_rejects_missing_source_column_and_duplicate_metadata_mapping() -> None:
    dataframe = _dataframe({"name": ["id"]})

    with pytest.raises(DataFrameSchemaMappingError):
        build_table_schema_from_dataframe(
            dataframe=dataframe,
            mapping=DataFrameSchemaMapping(column_names="missing"),
        )
    with pytest.raises(DataFrameSchemaMappingError):
        build_table_schema_from_dataframe(
            dataframe=dataframe,
            mapping=DataFrameSchemaMapping(column_names="name", metadata_columns=("name", "name")),
        )


def test_mapper_rejects_scale_greater_than_precision() -> None:
    dataframe = _dataframe({"name": ["amount"], "precision": [2], "scale": [3]})

    with pytest.raises(InvalidColumnSchemaError):
        build_table_schema_from_dataframe(
            dataframe=dataframe,
            mapping=DataFrameSchemaMapping(
                column_names="name",
                column_precision="precision",
                column_scale="scale",
            ),
        )
