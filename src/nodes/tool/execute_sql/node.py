import contextlib
from decimal import Decimal
from typing import Any

import dask.dataframe as dd
import pandas as pd
from sqlalchemy import Engine

from core.db.read_v3.sql_runner import read_sql_df
from core.types import DataFrameMetadata

from src.logger import logger
from src.modules.sql_code_metadata import (
    SQLAlchemyResultMetadataGateway,
    SQLCodeMetadataProvider,
    SQLGlotParserGateway,
)
from src.node_dsl import IO, DFOutputBaseNode, InputField, OutputField
from src.node_dsl.connection_types import SqlConnectionRecord
from src.node_dsl.node_mixins.sql import SQLCodeInputFieldMixin
from src.node_dsl.runtime.connections import resolve_sql_dialect_name, resolve_sql_engine
from src.node_dsl.variables import VariableOutput
from src.node_dsl.variables.type_system import (
    infer_variable_scalar_type_from_metadata_type,
    infer_variable_scalar_type_from_value,
)
from src.node_dsl.variables.types import VariableType


def _is_null_like(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except Exception:
        return False


def _normalize_variable_value(value: Any) -> Any:
    if _is_null_like(value):
        return None

    if hasattr(value, "item") and callable(getattr(value, "item")):  # noqa: B009
        with contextlib.suppress(Exception):
            value = value.item()

    if hasattr(value, "to_pydatetime") and callable(getattr(value, "to_pydatetime")):  # noqa: B009
        with contextlib.suppress(Exception):
            value = value.to_pydatetime()

    if hasattr(value, "to_pytimedelta") and callable(getattr(value, "to_pytimedelta")):  # noqa: B009
        with contextlib.suppress(Exception):
            value = value.to_pytimedelta()

    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, tuple):
        return list(value)
    return value


class ExecuteSQL(SQLCodeInputFieldMixin, DFOutputBaseNode):
    TITLE = "Execute SQL"
    EMOJI = "🧩"
    CATEGORY = "Tool"

    _sql_metadata_extractor = SQLCodeMetadataProvider(
        parser_gateway=SQLGlotParserGateway(),
        result_metadata_gateway=SQLAlchemyResultMetadataGateway(),
    ).create_extract_sql_code_metadata_use_case()

    connection: SqlConnectionRecord | Engine = InputField()

    signal_out: IO.SIGNAL = OutputField(description="Execution signal output", force_handle_visible=True)
    output: dd.DataFrame = OutputField(description="DataFrame output", force_handle_visible=True)
    output_variables: dict[str, IO.VARIABLE] = OutputField(
        description="Output variables",
        force_handle_visible=True,
    )

    def _get_engine(self) -> Engine:
        return resolve_sql_engine(self.connection)

    def get_dialect_name_for_sql_code_metadata(self) -> str | None:
        return resolve_sql_dialect_name(self.connection)

    def _read_resulting_dataframe(self, *, sql_code: str, returns_query_rows: bool) -> pd.DataFrame:
        engine = self._get_engine()
        if returns_query_rows:
            return read_sql_df(engine, sql_code)

        with engine.begin() as conn:
            result = conn.exec_driver_sql(sql_code)
            if not result.returns_rows:
                return pd.DataFrame()

            columns = list(result.keys())
            rows = result.fetchall()

        return pd.DataFrame(rows, columns=columns)

    @staticmethod
    def _resolve_variable_type(value: Any, dtype: Any) -> VariableType:
        metadata_type = infer_variable_scalar_type_from_metadata_type(dtype)
        if value is None:
            return metadata_type or IO.JSON

        value_type = infer_variable_scalar_type_from_value(value)
        if metadata_type is None or metadata_type == IO.JSON:
            return value_type
        return metadata_type

    def _populate_output_variables_from_single_row(self, output_pdf: pd.DataFrame) -> None:
        if len(output_pdf) != 1:
            return

        raw_column_names = list(output_pdf.columns)
        normalized_names = [str(column_name) for column_name in raw_column_names]
        duplicate_names = {
            column_name
            for column_name in normalized_names
            if normalized_names.count(column_name) > 1
        }

        next_output_variables = dict(self.output_variables or {})
        row = output_pdf.iloc[0]
        dtypes = list(output_pdf.dtypes)

        for index, column_name in enumerate(normalized_names):
            if not column_name.strip():
                logger.warning("Skipping ExecuteSQL variable for empty column name.")
                continue
            if column_name in duplicate_names:
                logger.warning(
                    f"Skipping ExecuteSQL variable for duplicate column name '{column_name}'."
                )
                continue

            value = _normalize_variable_value(row.iloc[index])
            variable_type = self._resolve_variable_type(value, dtypes[index])
            next_output_variables[column_name] = VariableOutput(
                name=column_name,
                type=variable_type,
                value=value,
                var_type="user",
            )

        self.output_variables = next_output_variables

    def process(self) -> None:
        sql_code = self._normalize_sql()
        sql_metadata = self.ensure_sql_code_metadata()
        returns_data = sql_metadata.result_statement_count > 0

        logger.info("Executing SQL tool node")
        try:
            if returns_data:
                output_pdf = self._read_resulting_dataframe(
                    sql_code=sql_code,
                    returns_query_rows=sql_metadata.statements[0].is_query_expression,
                )
                self.output = dd.from_pandas(output_pdf, npartitions=1)
                self._populate_output_variables_from_single_row(output_pdf)
            else:
                with self._get_engine().begin() as conn:
                    conn.exec_driver_sql(sql_code)
        except Exception as error:
            logger.error(f"Error while executing SQL code: {error}")
            raise

        self.signal_out = True

    async def process_metadata(self) -> None:
        sql_code = self._normalize_sql()
        sql_metadata = self.ensure_sql_code_metadata()
        self.signal_out = True
        if sql_metadata.result_statement_count == 0:
            return

        extracted_metadata = self._sql_metadata_extractor.execute(
            sql=sql_code,
            connection=self._get_engine(),
            dialect_name=self.get_dialect_name_for_sql_code_metadata(),
        )
        output_metadata = extracted_metadata.dataframe_metadata or DataFrameMetadata(columns=[])
        self.output = self.build_empty_ddf_from_metadata(output_metadata)
