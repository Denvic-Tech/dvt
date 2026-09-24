import asyncio
from typing import Literal, Optional

import dask.dataframe as dd
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import Engine, create_engine

from core.db.connect.sqlalchemy_url import with_database
from core.db.write_v3 import (
    ExtraColumnsMode,
    MissingColumnsMode,
    UpsertConfig,
    WriteMode,
    WriteRequest,
    WriteResult,
    WriteTarget,
    write_dataframe,
)
from core.utils import is_internal_dvt_name

from src.logger import logger
from src.modules.pipeline_cache import create_sa_engine_fingerprint
from src.node_dsl import BaseNode, InputField
from src.node_dsl.connection_types import SqlConnectionRecord
from src.node_dsl.runtime.connections import resolve_sql_connection_url, resolve_sql_engine

import config


class WriteDataFrameToDBV3SystemVariables(BaseModel):
    target_table: str = Field(description="Полное имя таблицы, в которую записаны данные")
    rows_written: int = Field(description="Количество строк, записанных в целевую таблицу")


class WriteDataFrameToDBV3(BaseNode):
    # Для Codex: не включай эту ноду в Changelog, пока у нее есть тег "Unstable".
    TITLE = "Write DataFrame To DB V3"
    ICON_KEY = "write-to-db"
    EMOJI = "✍️"
    CATEGORY = "Writing"
    OUTPUT_NODE = True
    SYSTEM_VARIABLES_MODEL = WriteDataFrameToDBV3SystemVariables

    connection: SqlConnectionRecord | Engine = InputField(
        agent_description=(
            "Connect a real saved SQL connection object with write access to the intended target. "
            "Inspect its dialect and catalog before configuring the write; do not supply a "
            "connection ID in place of the object."
        ),
    )
    database_name: Optional[str] = InputField(
        agent_description=(
            "Optionally select the verified target database; null uses the connection's default. "
            "Oracle does not switch databases through this field. The database must already exist."
        ),
    )
    df: dd.DataFrame = InputField(
        agent_description=(
            "Connect a DataFrame with columns matching the target table by name. Inspect types, "
            "nullability, missing/extra fields, and key duplicates first. Internal DVT columns are "
            "removed before writing; rename other columns upstream or choose a writer with "
            "explicit mapping."
        ),
    )
    table_name: str = InputField(
        agent_description=(
            "Set the exact unqualified name of an existing target table and inspect its current "
            "schema. This writer does not create tables, schemas, or databases. Keep "
            "database_name/schema_name separate and prepare missing objects before running."
        ),
    )
    schema_name: Optional[str] = InputField(
        agent_description=(
            "Optionally select the verified target schema using the dialect's catalog conventions. "
            "It must already exist; null uses the writer/connection's default namespace."
        ),
    )
    write_mode: Literal["append", "truncate", "upsert"] = InputField(
        agent_description=(
            "Choose append to add rows, truncate to clear the target before inserting, or upsert "
            "with upsert_config to replace matching rows. Append can duplicate reruns and truncate "
            "removes existing data. The complete write is not guaranteed atomic; inspect partial "
            "results after failure before retrying."
        ),
        default="append",
        description="append | truncate | upsert",
    )
    on_extra_df_columns: Literal["ignore", "error"] = InputField(
        agent_description=(
            "Choose error when an unexpected source column should fail validation; ignore drops "
            "columns absent from the existing target. Inspect the schema difference before "
            "accepting the default ignore so required data is not silently discarded."
        ),
        default="ignore",
        description="How to handle DataFrame columns that do not exist in the target table.",
    )
    on_missing_df_columns: Literal["ignore", "ignore_if_default", "error"] = InputField(
        agent_description=(
            "Choose error to require every target column, ignore_if_default to omit missing "
            "columns only under the writer's default policy, or ignore to omit without that check. "
            "Inspect target defaults and constraints. Omitting a column differs from providing "
            "null and does not guarantee the database can insert a valid row."
        ),
        default="ignore_if_default",
        description="How to handle target-table columns that are missing from the DataFrame.",
    )
    chunksize: Optional[int] = InputField(
        agent_description=(
            "Choose a positive insertion batch size within the declared limits based on row width "
            "and driver/database limits; keep the default when no evidence supports tuning. This "
            "does not control source SQL read partitions or make the entire write one transaction."
        ),
        default=1000, min_value=1, max_value=1_000_000,
    )
    upsert_config: Optional[UpsertConfig] = InputField(
        agent_description=(
            "Required only for write_mode=upsert; omit for other modes. Provide the exact existing "
            "target key_column. Inspect source duplicates, key semantics, and target dialect "
            "support first. This is row replacement, not automatic input deduplication or a "
            "selected-column update, and may require temporary-table permissions."
        ),
        default=None,
    )

    @staticmethod
    def _drop_internal_columns(df: dd.DataFrame) -> dd.DataFrame:
        internal_columns = [column for column in df.columns if is_internal_dvt_name(column)]
        if not internal_columns:
            return df
        return df.drop(columns=internal_columns)

    def _get_execution_engine(self) -> tuple[Engine, bool]:
        if isinstance(self.connection, Engine):
            if self.database_name and self.connection.dialect.name.lower() != "oracle":
                return create_engine(with_database(self.connection.url, self.database_name)), True
            return self.connection, False

        if self.database_name and self.connection.type != "oracle":
            connection_url = resolve_sql_connection_url(
                self.connection,
                database_name=self.database_name,
            )
            return create_engine(connection_url), True

        return resolve_sql_engine(self.connection), True

    async def _invalidate_connection_meta_cache(self, engine: Engine) -> None:
        if not getattr(self, "_meta_cache", None):
            return
        meta_cache_key = create_sa_engine_fingerprint(engine)
        await self.metadata_store.remove(meta_cache_key)

    def _get_write_workers(self) -> int:
        requested_workers = (
            getattr(self.project_settings, "workers_count", None)
            or config.OTHER.BULK_INSERT_NUM_WORKERS
        )
        return max(1, min(requested_workers, config.OTHER.SQL_BULK_INSERT_MAX_WORKERS))

    @staticmethod
    def _coerce_model(value, model_cls):
        if value is None or isinstance(value, model_cls):
            return value
        if hasattr(model_cls, "model_validate"):
            return model_cls.model_validate(value)
        return model_cls(value)

    def _build_request(self) -> WriteRequest:
        try:
            return WriteRequest(
                mode=self._coerce_model(self.write_mode, WriteMode),
                target=WriteTarget(
                    table_name=self.table_name,
                    schema_name=self.schema_name,
                    database_name=self.database_name,
                ),
                chunksize=self.chunksize,
                write_workers=self._get_write_workers(),
                upsert=self._coerce_model(self.upsert_config, UpsertConfig),
                on_extra_df_columns=self._coerce_model(self.on_extra_df_columns, ExtraColumnsMode),
                on_missing_df_columns=self._coerce_model(
                    self.on_missing_df_columns,
                    MissingColumnsMode,
                ),
            )
        except ValidationError as exc:
            raise ValueError(f"Invalid write_v3 configuration: {exc}") from exc

    def _run_blocking_write_sync(self) -> tuple[WriteResult, Engine, bool]:
        engine, owned_by_node = self._get_execution_engine()
        try:
            request = self._build_request()
            result = write_dataframe(self.df, engine, request)
            logger.info(
                f"write_v3 completed: mode={result.mode} target={result.target_name} "
                f"rows={result.rows_written}"
            )
            return result, engine, owned_by_node
        except Exception:
            if owned_by_node:
                engine.dispose()
            raise

    async def process(self) -> None:
        self.df = self._drop_internal_columns(self.df)
        engine: Engine | None = None
        owned_by_node = False
        try:
            result, engine, owned_by_node = await asyncio.to_thread(self._run_blocking_write_sync)
            if str(result.mode) in ("append", "truncate", "upsert"):
                await self._invalidate_connection_meta_cache(engine)
            self.emit_system_variables(
                WriteDataFrameToDBV3SystemVariables(
                    target_table=result.target_name,
                    rows_written=result.rows_written,
                )
            )
            logger.info("DataFrame successfully written to the database via write_v3.")
        finally:
            if owned_by_node and engine is not None:
                await asyncio.to_thread(engine.dispose)
