from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlglot import exp
from sqlalchemy.engine import Engine

from core.db.read_v3.query_metadata import describe_query_columns
from core.types import Column, DataFrameMetadata, DataType

from ..domain import SQLCodeMetadataError
from ..flow.gateways import ParsedSQLStatement, SQLResultMetadataGateway


class SQLAlchemyResultMetadataGateway(SQLResultMetadataGateway):
    """Строит DataFrameMetadata через SQLAlchemy schema introspection и read_v3 helpers."""

    _IDENTIFIER_TRIM_RE = re.compile(r"^[\\[`\"]+|[\\]`\"]+$")

    def build_dataframe_metadata(
        self,
        *,
        parsed_statement: ParsedSQLStatement,
        dialect_name: str | None,
        connection: Engine,
    ) -> DataFrameMetadata:
        if parsed_statement.metadata.is_query_expression:
            return self._build_query_dataframe_metadata(connection=connection, raw_query=parsed_statement.sql)

        if parsed_statement.metadata.statement_type in {"INSERT", "UPDATE", "DELETE"}:
            return self._build_dml_dataframe_metadata(
                connection=connection,
                parsed_statement=parsed_statement,
                dialect_name=dialect_name,
            )

        return DataFrameMetadata(columns=[])

    def _build_query_dataframe_metadata(self, *, connection: Engine, raw_query: str) -> DataFrameMetadata:
        described_columns = describe_query_columns(connection, raw_query)
        return DataFrameMetadata(
            columns=[
                Column(
                    name=str(column_name),
                    dtype=DataType.from_type(str(type_repr)),
                    nullable=True,
                    index=False,
                )
                for column_name, type_repr in described_columns
            ]
        )

    def _build_dml_dataframe_metadata(
        self,
        *,
        connection: Engine,
        parsed_statement: ParsedSQLStatement,
        dialect_name: str | None,
    ) -> DataFrameMetadata:
        target_table = self._extract_target_table(parsed_statement.expression)
        schema_columns = self._load_target_schema_columns(
            connection=connection,
            table_name=target_table["table_name"],
            schema_name=target_table["schema_name"],
        )

        returning = parsed_statement.expression.args.get("returning")
        if returning is None:
            return DataFrameMetadata(columns=[])

        expressions = returning.args.get("expressions") or []
        columns = [
            self._build_output_column(
                expression=expression,
                schema_columns=schema_columns,
                target_table=target_table,
                dialect_name=dialect_name,
            )
            for expression in expressions
        ]
        return DataFrameMetadata(columns=columns)

    def _extract_target_table(self, expression: exp.Expression) -> dict[str, Any]:
        target_expression = expression.args.get("this")
        if isinstance(target_expression, exp.Schema):
            target_expression = target_expression.this

        if not isinstance(target_expression, exp.Table):
            raise SQLCodeMetadataError("Failed to resolve target table for SQL result metadata.")

        aliases = {
            value
            for value in {
                target_expression.name,
                target_expression.alias,
                target_expression.alias_or_name,
                target_expression.db,
            }
            if isinstance(value, str) and value
        }
        aliases.update({"INSERTED", "inserted", "DELETED", "deleted"})
        return {
            "table_name": target_expression.name,
            "schema_name": target_expression.db,
            "aliases": aliases,
        }

    def _load_target_schema_columns(
        self,
        *,
        connection: Engine,
        table_name: str,
        schema_name: str | None,
    ) -> dict[str, dict[str, Any]]:
        inspector = sa.inspect(connection)
        try:
            columns = inspector.get_columns(table_name, schema=schema_name)
        except Exception as exc:
            raise SQLCodeMetadataError(
                f"Failed to load target table schema for '{table_name}'."
            ) from exc

        return {
            self._normalize_identifier(column["name"]): column
            for column in columns
            if isinstance(column, dict) and column.get("name")
        }

    def _build_output_column(
        self,
        *,
        expression: exp.Expression,
        schema_columns: dict[str, dict[str, Any]],
        target_table: dict[str, Any],
        dialect_name: str | None,
    ) -> Column:
        column_name = self._resolve_output_name(expression=expression, dialect_name=dialect_name)
        dtype, nullable = self._infer_expression_type(
            expression=expression,
            schema_columns=schema_columns,
            target_table=target_table,
            dialect_name=dialect_name,
        )
        return Column(
            name=column_name,
            dtype=dtype,
            nullable=nullable,
            index=False,
        )

    def _resolve_output_name(self, *, expression: exp.Expression, dialect_name: str | None) -> str:
        alias_or_name = expression.alias_or_name
        if alias_or_name:
            return alias_or_name

        if isinstance(expression, exp.Paren):
            return self._resolve_output_name(expression=expression.this, dialect_name=dialect_name)

        if dialect_name is None:
            return expression.sql()
        return expression.sql(dialect=dialect_name)

    def _infer_expression_type(
        self,
        *,
        expression: exp.Expression,
        schema_columns: dict[str, dict[str, Any]],
        target_table: dict[str, Any],
        dialect_name: str | None,
    ) -> tuple[DataType, bool | None]:
        if isinstance(expression, exp.Alias):
            return self._infer_expression_type(
                expression=expression.this,
                schema_columns=schema_columns,
                target_table=target_table,
                dialect_name=dialect_name,
            )

        if isinstance(expression, exp.Paren):
            return self._infer_expression_type(
                expression=expression.this,
                schema_columns=schema_columns,
                target_table=target_table,
                dialect_name=dialect_name,
            )

        if isinstance(expression, exp.Column):
            return self._infer_column_type(
                expression=expression,
                schema_columns=schema_columns,
                target_table=target_table,
            )

        if isinstance(expression, (exp.Cast, exp.TryCast)):
            target_type = expression.args.get("to")
            type_repr = ""
            if target_type is not None:
                if dialect_name is None:
                    type_repr = target_type.sql()
                else:
                    type_repr = target_type.sql(dialect=dialect_name)
            return DataType.from_type(type_repr), None

        if isinstance(expression, exp.Boolean):
            return DataType.BOOLEAN, False

        if isinstance(expression, exp.Null):
            return DataType.UNKNOWN, True

        if isinstance(expression, exp.Literal):
            return self._infer_literal_type(expression)

        child_results = [
            self._infer_expression_type(
                expression=child_expression,
                schema_columns=schema_columns,
                target_table=target_table,
                dialect_name=dialect_name,
            )
            for child_expression in expression.iter_expressions()
            if isinstance(child_expression, exp.Expression)
        ]
        known_dtypes = {dtype for dtype, _ in child_results if dtype != DataType.UNKNOWN}
        if len(known_dtypes) == 1:
            nullable_values = {nullable for _, nullable in child_results if nullable is not None}
            nullable = None if not nullable_values else True if True in nullable_values else False
            return next(iter(known_dtypes)), nullable

        return DataType.UNKNOWN, None

    def _infer_literal_type(self, expression: exp.Literal) -> tuple[DataType, bool | None]:
        if expression.is_string:
            return DataType.STRING, False

        literal_value = str(expression.this)
        lowered_value = literal_value.lower()
        if lowered_value in {"true", "false"}:
            return DataType.BOOLEAN, False

        try:
            int(literal_value)
        except (TypeError, ValueError):
            pass
        else:
            return DataType.INT, False

        try:
            Decimal(literal_value)
        except Exception:
            return DataType.UNKNOWN, None

        return DataType.FLOAT, False

    def _infer_column_type(
        self,
        *,
        expression: exp.Column,
        schema_columns: dict[str, dict[str, Any]],
        target_table: dict[str, Any],
    ) -> tuple[DataType, bool | None]:
        table_name = expression.table
        if table_name:
            normalized_table_name = self._normalize_identifier(table_name)
            normalized_aliases = {self._normalize_identifier(alias) for alias in target_table["aliases"]}
            if normalized_table_name not in normalized_aliases:
                return DataType.UNKNOWN, None

        normalized_column_name = self._normalize_identifier(expression.name)
        column = schema_columns.get(normalized_column_name)
        if column is None:
            return DataType.UNKNOWN, None

        return self._resolve_inspector_dtype(column.get("type")), self._coerce_nullable(column.get("nullable"))

    def _resolve_inspector_dtype(self, column_type: Any) -> DataType:
        if column_type is None:
            return DataType.UNKNOWN

        try:
            python_type = column_type.python_type
        except Exception:
            python_type = None

        if python_type is not None:
            dtype = DataType.from_type(python_type)
            if dtype != DataType.UNKNOWN:
                return dtype

        dtype = DataType.from_type(str(column_type))
        if dtype != DataType.UNKNOWN:
            return dtype

        return DataType.from_type(type(column_type).__name__)

    def _coerce_nullable(self, value: Any) -> bool | None:
        if value is None:
            return None
        return bool(value)

    def _normalize_identifier(self, value: str) -> str:
        normalized = self._IDENTIFIER_TRIM_RE.sub("", value.strip())
        return normalized.lower()
