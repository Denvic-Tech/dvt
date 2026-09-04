from typing import Optional

import dask.dataframe as dd

from core.types import TableSchemaColumnMetadata, TableSchemaMetadata

from src.modules.data_catalog import (
    DataFrameSchemaMapping,
    TableSchema,
    build_table_schema_from_dataframe,
)
from src.modules.data_catalog.domain import DataCatalogDomainError
from src.modules.data_catalog.infra import DataCatalogInfraError
from src.node_dsl import BaseNode, InputField, NodeValidationError, OutputField
from src.node_dsl.node_typing import IO
from src.node_dsl.types import NodeMetadata


class ConvertToSchema(BaseNode):
    TITLE = "Convert To Schema"
    CATEGORY = "Tool"

    df: dd.DataFrame = InputField()
    column_names: IO.COLUMN_NAME = InputField()
    column_dtypes: Optional[IO.COLUMN_NAME] = InputField(default=None)
    column_descriptions: Optional[IO.COLUMN_NAME] = InputField(default=None)
    column_nullable: Optional[IO.COLUMN_NAME] = InputField(default=None)
    column_defaults: Optional[IO.COLUMN_NAME] = InputField(default=None)
    column_order: Optional[IO.COLUMN_NAME] = InputField(default=None)
    column_primary_key: Optional[IO.COLUMN_NAME] = InputField(default=None)
    column_unique: Optional[IO.COLUMN_NAME] = InputField(default=None)
    column_precision: Optional[IO.COLUMN_NAME] = InputField(default=None)
    column_scale: Optional[IO.COLUMN_NAME] = InputField(default=None)
    column_length: Optional[IO.COLUMN_NAME] = InputField(default=None)
    column_format: Optional[IO.COLUMN_NAME] = InputField(default=None)
    metadata_columns: Optional[list[IO.COLUMN_NAME]] = InputField(default=None)

    schema: TableSchema = OutputField()

    def _mapping(self) -> DataFrameSchemaMapping:
        return DataFrameSchemaMapping(
            column_names=self.column_names,
            column_dtypes=self.column_dtypes,
            column_descriptions=self.column_descriptions,
            column_nullable=self.column_nullable,
            column_defaults=self.column_defaults,
            column_order=self.column_order,
            column_primary_key=self.column_primary_key,
            column_unique=self.column_unique,
            column_precision=self.column_precision,
            column_scale=self.column_scale,
            column_length=self.column_length,
            column_format=self.column_format,
            metadata_columns=tuple(self.metadata_columns or ()),
        )

    @staticmethod
    def _error_message(exc: DataCatalogDomainError | DataCatalogInfraError) -> str:
        return str(exc.exc_data or exc.description)

    def process(self) -> None:
        try:
            self.schema = build_table_schema_from_dataframe(
                dataframe=self.df,
                mapping=self._mapping(),
            )
        except (DataCatalogDomainError, DataCatalogInfraError) as exc:
            raise NodeValidationError(self._error_message(exc)) from exc

    def process_metadata(self) -> None:
        self.schema = TableSchema()

    def infer_metadata(self) -> NodeMetadata:
        if not isinstance(self.schema, TableSchema):
            raise TypeError("ConvertToSchema expected TableSchema for schema output")

        return {
            "schema": TableSchemaMetadata(
                columns=[
                    TableSchemaColumnMetadata(
                        name=column.name,
                        dtype=column.dtype,
                        description=column.description,
                        nullable=column.nullable,
                        default=column.default,
                        order=column.order,
                        primary_key=column.primary_key,
                        unique=column.unique,
                        precision=column.precision,
                        scale=column.scale,
                        length=column.length,
                        format=column.format,
                        metadata=dict(column.metadata),
                    )
                    for column in self.schema.columns
                ]
            )
        }
