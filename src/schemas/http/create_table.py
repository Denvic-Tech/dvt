from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from core.db.ddl import AppliedTableColumnAction, TableColumnAction, TableCreateSpec
from core.db.write_v4 import (
    ExtraColumnsMode,
    MissingColumnsMode,
    WriteColumnMapping,
    WriteColumnResolutionResult,
    WriteDiagnostic,
)
from core.types import DataFrameMetadata, DBColumn, DBTable

OnExistsMode = Literal["ignore", "recreate", "error"]


class GenerateTableDDL(BaseModel):
    dataframe_metadata: DataFrameMetadata | None = None
    connection_id: str = Field(..., min_length=1)
    table_name: str = Field(..., min_length=1)
    database_name: Optional[str] = None
    schema_name: Optional[str] = None
    index_col: Optional[str | List[str]] = None
    columns: List[DBColumn] | None = None
    table_create_spec: Optional[TableCreateSpec] = None


class GenerateTableDDLResponse(BaseModel):
    sql: str


class ResolveWriteColumnsRequest(BaseModel):
    mode: Literal["existing_table", "typed_create"]
    connection_id: str = Field(..., min_length=1)
    table_name: str = Field(..., min_length=1)
    database_name: Optional[str] = None
    schema_name: Optional[str] = None
    dataframe_metadata: DataFrameMetadata
    column_mapping: List[WriteColumnMapping] | None = None
    on_extra_df_columns: ExtraColumnsMode = ExtraColumnsMode.IGNORE
    on_missing_df_columns: MissingColumnsMode = MissingColumnsMode.IGNORE_IF_DEFAULT
    table_create_spec: Optional[TableCreateSpec] = None


class ResolveWriteColumnsResponse(WriteColumnResolutionResult):
    pass


class ApplyTableColumnActionsRequest(BaseModel):
    connection_id: str = Field(..., min_length=1)
    table_name: str = Field(..., min_length=1)
    database_name: Optional[str] = None
    schema_name: Optional[str] = None
    actions: List[TableColumnAction] = Field(min_length=1)
    dry_run: bool = False


class ApplyTableColumnActionsResponse(BaseModel):
    success: bool = True
    message: str
    sql: List[str] = Field(default_factory=list)
    applied_actions: List[AppliedTableColumnAction] = Field(default_factory=list)
    diagnostics: List[WriteDiagnostic] = Field(default_factory=list)
    table_metadata: DBTable | None = None


class RecreateTableRequest(BaseModel):
    connection_id: str = Field(..., min_length=1)
    table_name: str = Field(..., min_length=1)
    database_name: str | None = None
    schema_name: str | None = None
    columns: list[DBColumn] = Field(min_length=1)
    table_create_spec: TableCreateSpec | None = None


class TruncateTableRequest(BaseModel):
    connection_id: str = Field(..., min_length=1)
    table_name: str = Field(..., min_length=1)
    database_name: str | None = None
    schema_name: str | None = None


class TableDDLActionResponse(BaseModel):
    success: bool = True
    message: str
    table_metadata: DBTable


class CreateTableFromSchemaRequest(BaseModel):
    mode: Literal["from_schema"] = "from_schema"
    table_name: str = Field(..., min_length=1)
    connection_id: str = Field(..., min_length=1)
    database_name: Optional[str] = None
    schema_name: Optional[str] = None
    columns: List[DBColumn]
    table_create_spec: Optional[TableCreateSpec] = None
    on_exists: OnExistsMode = "error"


class CreateTableFromSQLRequest(BaseModel):
    mode: Literal["from_sql"] = "from_sql"
    connection_id: str = Field(..., min_length=1)
    table_ddl: str = Field(..., min_length=1)
    database_name: Optional[str] = None
    schema_name: Optional[str] = None
    on_exists: OnExistsMode = "error"


CreateTableRequest = Annotated[
    Union[CreateTableFromSchemaRequest, CreateTableFromSQLRequest],
    Field(discriminator="mode"),
]


CreateTableFromDDLRequest = CreateTableFromSQLRequest


class CreateDatabaseRequest(BaseModel):
    connection_id: str = Field(..., min_length=1)
    database_name: str = Field(..., min_length=1)


class CreateSchemaRequest(BaseModel):
    connection_id: str = Field(..., min_length=1)
    schema_name: str = Field(..., min_length=1)
    database_name: Optional[str] = None


class GenerateSchemaDDLRequest(BaseModel):
    connection_id: str = Field(..., min_length=1)
    schema_name: str = Field(..., min_length=1)
    database_name: Optional[str] = None


class GenerateSchemaDDLResponse(BaseModel):
    sql: str
