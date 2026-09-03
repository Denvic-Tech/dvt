import dask.dataframe as dd
import pandas as pd
import pytest

from core.types import TableSchemaColumnMetadata, TableSchemaMetadata

from src.modules.data_catalog.domain import TableSchema
from src.node_dsl import IO, NodeValidationError
from src.nodes.tool.convert_to_schema import ConvertToSchema


def _build_node(dataframe: dd.DataFrame, **kwargs: object) -> ConvertToSchema:
    return ConvertToSchema(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="convert-to-schema-1",
        df=dataframe,
        column_names="name",
        **kwargs,
    )


def test_convert_to_schema_builds_table_schema() -> None:
    dataframe = dd.from_pandas(
        pd.DataFrame({"name": ["second", "first"], "position": [2, 1]}),
        npartitions=1,
    )
    node = _build_node(dataframe, column_order="position")

    node.process()

    assert isinstance(node.schema, TableSchema)
    assert [column.name for column in node.schema.columns] == ["first", "second"]
    assert node.output_fields()["schema"].resolved_type is IO.TABLE_SCHEMA


def test_convert_to_schema_metadata_does_not_compute_input() -> None:
    dataframe = dd.from_pandas(pd.DataFrame({"name": ["id"]}), npartitions=1)
    node = _build_node(dataframe)

    node.process_metadata()
    metadata = node.infer_metadata()["schema"]

    assert node.schema == TableSchema()
    assert metadata == TableSchemaMetadata()


def test_convert_to_schema_infers_complete_table_schema_metadata() -> None:
    dataframe = dd.from_pandas(
        pd.DataFrame(
            {
                "name": ["amount"],
                "dtype": ["NUMERIC"],
                "description": ["Monetary amount"],
                "nullable": [False],
                "default": [0],
                "position": [2],
                "primary_key": [False],
                "unique": [True],
                "precision": [18],
                "scale": [2],
                "length": [32],
                "format": ["0.00"],
                "source": ["billing"],
            }
        ),
        npartitions=1,
    )
    node = _build_node(
        dataframe,
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
        metadata_columns=["source"],
    )

    node.process()
    metadata = node.infer_metadata()["schema"]

    assert metadata == TableSchemaMetadata(
        columns=[
            TableSchemaColumnMetadata(
                name="amount",
                dtype="NUMERIC",
                description="Monetary amount",
                nullable=False,
                default=0,
                order=2,
                primary_key=False,
                unique=True,
                precision=18,
                scale=2,
                length=32,
                format="0.00",
                metadata={"source": "billing"},
            )
        ]
    )


def test_convert_to_schema_exposes_mapping_errors_as_node_validation_errors() -> None:
    dataframe = dd.from_pandas(pd.DataFrame({"name": ["id", "id"]}), npartitions=1)
    node = _build_node(dataframe)

    with pytest.raises(NodeValidationError, match="duplicate column names"):
        node.process()
