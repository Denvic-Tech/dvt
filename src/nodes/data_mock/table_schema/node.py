from core.types import TableSchemaColumnMetadata, TableSchemaMetadata

from src.modules.data_catalog import ColumnSchema, TableSchema
from src.node_dsl import BaseNode, OutputField
from src.node_dsl.types import NodeMetadata

HARDCODED_TABLE_SCHEMA = TableSchema(
    columns=(
        ColumnSchema(
            name="id",
            dtype="BIGINT",
            description="Row identifier",
            nullable=False,
            order=0,
            primary_key=True,
            unique=True,
        ),
        ColumnSchema(
            name="name",
            dtype="TEXT",
            description="Display name",
            nullable=False,
            order=1,
            length=255,
        ),
        ColumnSchema(
            name="amount",
            dtype="NUMERIC",
            description="Monetary amount",
            nullable=True,
            default=0,
            order=2,
            precision=18,
            scale=2,
        ),
        ColumnSchema(
            name="created_at",
            dtype="TIMESTAMPTZ",
            description="Creation timestamp",
            nullable=False,
            order=3,
        ),
    )
)


def _build_table_schema_metadata(schema: TableSchema) -> TableSchemaMetadata:
    return TableSchemaMetadata(
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
            for column in schema.columns
        ]
    )


class GetMockTableSchema(BaseNode):
    TITLE = "Get Mock Table Schema"
    EMOJI = "🧱"
    CATEGORY = "Mock Data"
    DESCRIPTION = "Return a fixed TableSchema for UI and metadata testing."
    CACHABLE = False
    TAGS = frozenset({"Testing"})

    schema: TableSchema = OutputField(description="Hardcoded table schema.")

    def process(self) -> None:
        self.schema = HARDCODED_TABLE_SCHEMA

    def process_metadata(self) -> None:
        self.process()

    def infer_metadata(self) -> NodeMetadata:
        schema = getattr(self, "schema", None)
        if not isinstance(schema, TableSchema):
            schema = HARDCODED_TABLE_SCHEMA
        return {"schema": _build_table_schema_metadata(schema)}
