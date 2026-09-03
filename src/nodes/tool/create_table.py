import asyncio
from typing import Literal, Optional

import sqlalchemy as sa
from pydantic import BaseModel, Field
from sqlalchemy import Engine, create_engine

from core.db.ddl import (
    TableCreateSpec,
    build_db_columns_from_df_metadata,
    create_typed_table_from_columns,
    get_primary_key_cols,
    normalize_db_columns_nullable_for_ddl,
    resolve_metadata_schema_for_ddl,
)
from core.types import DataFrameMetadata

from src.logger import logger
from src.modules.pipeline_cache import create_sa_engine_fingerprint
from src.node_dsl import InputField, SignalOutputBaseNode
from src.node_dsl.connection_types import SqlConnectionRecord
from src.node_dsl.runtime.connections import resolve_sql_engine


def normalize_df_metadata(
        *,
        metadata: DataFrameMetadata | dict,
):
    if isinstance(metadata, dict):
        metadata = DataFrameMetadata.model_validate(metadata)

    if not isinstance(metadata, DataFrameMetadata):
        raise ValueError(f"value is not a DataFrameMetadata")

    return metadata


def normalize_table_create_spec(
        *,
        spec: TableCreateSpec | dict | None,
):
    if spec is None:
        return None

    if isinstance(spec, dict):
        spec = TableCreateSpec.model_validate(spec)

    if not isinstance(spec, TableCreateSpec):
        raise ValueError(f"value is not a TableCreateSpec")

    return spec


class SystemVariables(BaseModel):
    target_table_name: str = Field(..., description=f"Target table name")
    target_schema_name: Optional[str] = Field(..., description=f"Target schema name")
    target_db_name: Optional[str] = Field(..., description=f"Target database name")


class CreateTable(SignalOutputBaseNode):
    TITLE = "Create Table"
    EMOJI = "🧱"
    CATEGORY = "Tool"
    SYSTEM_VARIABLES_MODEL = SystemVariables

    connection: SqlConnectionRecord | Engine = InputField()
    database_name: Optional[str] = InputField()
    schema_name: Optional[str] = InputField()
    table_name: str = InputField()
    dataframe_metadata: DataFrameMetadata = InputField()
    table_create_spec: Optional[TableCreateSpec] = InputField(default=None)
    on_exists: Literal["ignore", "recreate", "error"] = InputField(
        default="error",
        description="ignore | recreate | error",
    )

    _actual_connection: Optional[Engine] = None

    def _create_new_connection(self) -> Engine:
        if self._actual_connection is not None:
            return self._actual_connection

        base_engine = resolve_sql_engine(self.connection)
        if self.database_name and base_engine.dialect.name.lower() != "oracle":
            self._actual_connection = create_engine(base_engine.url.set(database=self.database_name))
        else:
            self._actual_connection = base_engine

        return self._actual_connection

    def _get_effective_schema_name(self, engine: Engine) -> str | None:
        effective_database_name = self.database_name or engine.url.database
        return resolve_metadata_schema_for_ddl(
            dialect_name=engine.dialect.name,
            schema_name=self.schema_name,
            database_name=effective_database_name,
        )

    def _build_db_columns(
        self,
        engine: Engine,
    ) -> tuple[list, str | list[str] | None]:
        db_columns = build_db_columns_from_df_metadata(self.dataframe_metadata)
        inferred_primary_key_cols = get_primary_key_cols(index_col=None, columns=db_columns)
        effective_primary_key_cols = (
            self.table_create_spec.primary_key_cols
            if self.table_create_spec and self.table_create_spec.primary_key_cols is not None
            else inferred_primary_key_cols
        )
        normalized_columns = normalize_db_columns_nullable_for_ddl(
            dialect_name=engine.dialect.name,
            columns=db_columns,
            primary_key_cols=effective_primary_key_cols,
        )
        return normalized_columns, inferred_primary_key_cols

    async def _invalidate_connection_meta_cache(self) -> None:
        if not getattr(self, "_meta_cache", None):
            return
        meta_cache_key = create_sa_engine_fingerprint(self._create_new_connection())
        await self.metadata_store.remove(meta_cache_key)

    def _create_table_sync(self) -> bool:
        engine = self._create_new_connection()
        effective_schema_name = self._get_effective_schema_name(engine)
        inspector = sa.inspect(engine)

        table_exists = inspector.has_table(self.table_name, schema=effective_schema_name)
        if table_exists:
            match self.on_exists:
                case "error":
                    raise ValueError(f'Table "{self.table_name}" already exists.')
                case "ignore":
                    logger.info(
                        "CreateTableFromMetadata skipped existing table",
                        table_name=self.table_name,
                        schema_name=effective_schema_name,
                    )
                    return False
                case "recreate":
                    table = sa.Table(
                        self.table_name,
                        sa.MetaData(),
                        schema=effective_schema_name,
                        autoload_with=engine,
                    )
                    table.drop(engine, checkfirst=True)
                    logger.info(
                        "CreateTableFromMetadata dropped existing table before recreate",
                        table_name=self.table_name,
                        schema_name=effective_schema_name,
                    )

        columns, inferred_primary_key_cols = self._build_db_columns(engine)
        if not columns:
            raise ValueError("dataframe_metadata.columns is empty.")

        create_typed_table_from_columns(
            engine=engine,
            table_name=self.table_name,
            columns=columns,
            schema_name=effective_schema_name,
            primary_key_cols=inferred_primary_key_cols,
            spec=self.table_create_spec,
        )
        logger.info(
            "CreateTableFromMetadata finished",
            table_name=self.table_name,
            schema_name=effective_schema_name,
            on_exists=self.on_exists,
        )
        return True

    async def process(self) -> None:
        self.dataframe_metadata = normalize_df_metadata(metadata=self.dataframe_metadata)
        self.table_create_spec = normalize_table_create_spec(spec=self.table_create_spec)

        table_changed = await asyncio.to_thread(self._create_table_sync)
        if table_changed:
            await self._invalidate_connection_meta_cache()
        self.signal_out = True
        self.emit_system_variables(SystemVariables(
            target_table_name=self.table_name,
            target_schema_name=self.schema_name,
            target_db_name=self.database_name,
        ))

    async def process_metadata(self) -> None:
        self.signal_out = True
        self.emit_system_variables(SystemVariables(
            target_table_name=self.table_name,
            target_schema_name=self.schema_name,
            target_db_name=self.database_name,
        ))
