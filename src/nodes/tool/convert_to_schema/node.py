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
    ICON_KEY = "convert-to-schema"
    CATEGORY = "Tool"

    df: dd.DataFrame = InputField(
        agent_description=(
            "Connect a descriptor DataFrame where each row describes one target field. This reads "
            "descriptor values, not the DataFrame's own dtypes as a schema. Full execution "
            "computes selected descriptor columns into memory; metadata-only mode produces an "
            "empty TableSchema."
        ),
    )
    column_names: IO.COLUMN_NAME = InputField(
        agent_description=(
            "Name the descriptor-table column containing non-empty target field names. This is a "
            "source column reference, not a list of target names. Verify uniqueness of the "
            "resulting schema names and remove malformed descriptor rows."
        ),
    )
    column_dtypes: Optional[IO.COLUMN_NAME] = InputField(
        agent_description=(
            "Optionally name the descriptor column containing target dtype strings. Null leaves "
            "dtype unspecified. Choose type names understood by the downstream schema consumer; "
            "this stores metadata and does not cast business data."
        ),
        default=None,
    )
    column_descriptions: Optional[IO.COLUMN_NAME] = InputField(
        agent_description=(
            "Optionally name the descriptor column containing human-readable descriptions for "
            "target fields. Values must be strings or null; surrounding whitespace is trimmed."
        ),
        default=None,
    )
    column_nullable: Optional[IO.COLUMN_NAME] = InputField(
        agent_description=(
            "Optionally name the descriptor column containing nullable flags. Accepted non-null "
            "values are Booleans, numeric 0/1, or true/false strings. Null leaves the property "
            "unspecified; this mapping itself does not validate data nullability."
        ),
        default=None,
    )
    column_defaults: Optional[IO.COLUMN_NAME] = InputField(
        agent_description=(
            "Optionally name the descriptor column containing default values for target fields. "
            "Values are preserved as schema metadata with missing values normalized to null; they "
            "are not evaluated as expressions or automatically applied to business rows."
        ),
        default=None,
    )
    column_order: Optional[IO.COLUMN_NAME] = InputField(
        agent_description=(
            "Optionally name the descriptor column containing non-negative integer positions. When "
            "configured, every row needs a non-null order value. Verify ordering before relying on "
            "the resulting schema; omit to use the builder's default ordering."
        ),
        default=None,
    )
    column_primary_key: Optional[IO.COLUMN_NAME] = InputField(
        agent_description=(
            "Optionally name the descriptor column containing primary-key flags. Use Booleans, "
            "numeric 0/1, true/false strings, or null. The resulting metadata describes intent and "
            "does not check uniqueness or create a database constraint."
        ),
        default=None,
    )
    column_unique: Optional[IO.COLUMN_NAME] = InputField(
        agent_description=(
            "Optionally name the descriptor column containing uniqueness flags, as Booleans, "
            "numeric 0/1, true/false strings, or null. This records a schema property rather than "
            "performing duplicate detection."
        ),
        default=None,
    )
    column_precision: Optional[IO.COLUMN_NAME] = InputField(
        agent_description=(
            "Optionally name the descriptor column containing non-negative integer precision "
            "values or null. Choose precision from the target type and actual value range; this "
            "node records the value without converting data."
        ),
        default=None,
    )
    column_scale: Optional[IO.COLUMN_NAME] = InputField(
        agent_description=(
            "Optionally name the descriptor column containing non-negative integer scale values or "
            "null. Keep scale consistent with precision and the downstream decimal type contract; "
            "no rounding is performed here."
        ),
        default=None,
    )
    column_length: Optional[IO.COLUMN_NAME] = InputField(
        agent_description=(
            "Optionally name the descriptor column containing non-negative integer length limits "
            "or null. Use a size appropriate to source values and the target consumer; this does "
            "not truncate or validate business strings."
        ),
        default=None,
    )
    column_format: Optional[IO.COLUMN_NAME] = InputField(
        agent_description=(
            "Optionally name the descriptor column containing format strings or null. These are "
            "descriptive schema attributes, not an instruction to parse or reformat the input "
            "DataFrame."
        ),
        default=None,
    )
    metadata_columns: Optional[list[IO.COLUMN_NAME]] = InputField(
        agent_description=(
            "Optionally list additional distinct descriptor columns to retain in each target "
            "field's metadata dictionary. All names must exist and be unambiguous. Select only "
            "useful attributes; values are collected into memory along with the descriptor rows."
        ),
        default=None,
    )

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
