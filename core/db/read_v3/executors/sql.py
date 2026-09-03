from __future__ import annotations

import re
from typing import Optional

import pandas as pd
from sqlalchemy.engine import Engine

from core.db.read_v3.datetime_precision import pandas_datetime_dtype
from core.db.read_v3.dialects import resolve_dialect
from core.db.read_v3.dialects.base import SQLDialect
from core.db.read_v3.errors import ReadV3ExecutionError
from core.db.read_v3.executors.base import Executor
from core.db.read_v3.models import PartitionStrategy, ReadSegment, ReadV3Plan, ValueKind
from core.db.read_v3.sql_runner import ReadV3SqlRunner, resolve_sql_runner


class SQLReadExecutor(Executor):
    @staticmethod
    def _is_mssql_binary_type_repr(type_repr: str) -> bool:
        raw = (type_repr or "").lower().strip()
        return raw.startswith(("binary", "varbinary", "image", "rowversion", "timestamp"))

    @classmethod
    def _uses_raw_mssql_partition_index(cls, plan: ReadV3Plan) -> bool:
        return (
            plan.dialect == "mssql"
            and plan.index_column_name == plan.partition_key_alias
            and (
                cls._is_mssql_binary_type_repr(plan.partition_key_type_repr)
                or "uniqueidentifier" in (plan.partition_key_type_repr or "").lower()
            )
        )

    def __init__(self, engine: Engine, *, dialect: SQLDialect | None = None):
        self.engine = engine
        self.dialect = dialect or resolve_dialect(engine)
        self.sql_runner: ReadV3SqlRunner = resolve_sql_runner(engine)

    def _wrap_sql(self, plan: ReadV3Plan, sql: str) -> str:
        if plan.cte_prefix_sql:
            return f"{plan.cte_prefix_sql} {sql}"
        return sql

    def _segment_sql(self, plan: ReadV3Plan, segment: ReadSegment) -> str:
        select_list = plan.select_list_sql()
        if segment.index_literal is not None:
            index_alias = self.dialect.quote_ident(plan.index_column_name)
            select_list = f"{select_list}, {int(segment.index_literal)} AS {index_alias}"

        return self._wrap_sql(
            plan,
            (
                f"SELECT {select_list} {plan.relation_sql} "
                f"WHERE {segment.predicate_sql} {segment.order_by_sql}"
            ),
        )

    def _read_sql_bounded(self, sql: str, max_rows: int) -> pd.DataFrame:
        if max_rows <= 0:
            raise ReadV3ExecutionError("max_rows_per_partition must be positive")

        capped_sql = self.dialect.cap_rows_sql(sql, max_rows + 1)
        df = self.sql_runner.query_df(capped_sql)
        if len(df) > max_rows:
            raise ReadV3ExecutionError(
                f"Segment exceeded max_rows_per_partition={max_rows}; rows_read={len(df)}"
            )
        return df

    @staticmethod
    def _normalize_column_name(name: object) -> str:
        return str(name).strip().strip("[]`\"").lower()

    @staticmethod
    def _source_name(plan: ReadV3Plan) -> str:
        return plan.source_name()

    @classmethod
    def _resolve_column_name(cls, columns: pd.Index, expected: str) -> object | None:
        if expected in columns:
            return expected

        normalized_expected = cls._normalize_column_name(expected)
        for column in columns:
            if cls._normalize_column_name(column) == normalized_expected:
                return column
        return None

    def _pick_index_column(self, plan: ReadV3Plan, df: pd.DataFrame) -> str:
        resolved_index = self._resolve_column_name(df.columns, plan.index_column_name)
        if resolved_index is not None:
            return resolved_index

        if plan.strategy == PartitionStrategy.RANGE:
            resolved_partition_key = self._resolve_column_name(df.columns, plan.partition_key_name)
            if resolved_partition_key is not None:
                return resolved_partition_key

            resolved_partition_alias = self._resolve_column_name(df.columns, plan.partition_key_alias)
            if resolved_partition_alias is not None:
                return resolved_partition_alias

            raise ReadV3ExecutionError(
                f"Range segment is missing partition key columns: {plan.partition_key_name!r}, "
                f"{plan.partition_key_alias!r}"
            )

        if plan.strategy == PartitionStrategy.HASH:
            resolved_hash_bucket = self._resolve_column_name(df.columns, plan.hash_bucket_alias)
            if resolved_hash_bucket is None:
                raise ReadV3ExecutionError(
                    f"Hash segment is missing helper bucket column {plan.hash_bucket_alias!r}"
                )
            return resolved_hash_bucket

        raise ReadV3ExecutionError(f"Unsupported strategy for index selection: {plan.strategy.value}")

    @staticmethod
    def _validate_index_bounds(df: pd.DataFrame, segment: ReadSegment) -> None:
        if df.empty:
            return

        index_min = df.index.min()
        index_max = df.index.max()
        start = segment.division.start
        end = segment.division.end

        try:
            if index_min < start:
                raise ReadV3ExecutionError(
                    f"Segment index lower bound violation: min={index_min!r} start={start!r}"
                )
            if segment.division.include_end:
                if index_max > end:
                    raise ReadV3ExecutionError(
                        f"Segment index upper bound violation: max={index_max!r} end={end!r}"
                    )
            else:
                if index_max >= end:
                    raise ReadV3ExecutionError(
                        f"Segment index upper bound violation (exclusive): max={index_max!r} end={end!r}"
                    )
        except TypeError as exc:
            raise ReadV3ExecutionError(
                f"Segment index values are not comparable with divisions: min={index_min!r}, max={index_max!r}, "
                f"start={start!r}, end={end!r}"
            ) from exc

    @classmethod
    def _resolve_output_columns(
        cls,
        df: pd.DataFrame,
        plan: ReadV3Plan,
    ) -> dict[str, object]:
        resolved_output_columns: dict[str, str] = {}
        missing: list[str] = []
        for output_column in plan.output_columns:
            resolved = cls._resolve_column_name(df.columns, output_column)
            if resolved is None:
                missing.append(output_column)
            else:
                resolved_output_columns[output_column] = resolved

        if missing:
            raise ReadV3ExecutionError(f"Segment is missing required output columns: {missing!r}")
        return resolved_output_columns

    @classmethod
    def _project_output_columns(
        cls,
        df: pd.DataFrame,
        plan: ReadV3Plan,
    ) -> pd.DataFrame:
        resolved_output_columns = cls._resolve_output_columns(df, plan)
        projected = df[[resolved_output_columns[column] for column in plan.output_columns]].copy()
        projected.columns = list(plan.output_columns)
        return projected

    @classmethod
    def _finalize_output(cls, df: pd.DataFrame, plan: ReadV3Plan) -> pd.DataFrame:
        resolved_output_columns = cls._resolve_output_columns(df, plan)

        normalized_output = {
            cls._normalize_column_name(column)
            for column in plan.output_columns
        }
        normalized_helpers = {
            cls._normalize_column_name(plan.partition_key_alias),
            cls._normalize_column_name(plan.hash_bucket_alias),
        }
        drop_candidates = []
        for column in df.columns:
            normalized = cls._normalize_column_name(column)
            if normalized in normalized_helpers and normalized not in normalized_output:
                drop_candidates.append(column)
        if drop_candidates:
            for column in drop_candidates:
                del df[column]

        projected = df[[resolved_output_columns[column] for column in plan.output_columns]].copy()
        projected.columns = list(plan.output_columns)
        return projected

    @staticmethod
    def _is_integer_type_repr(type_repr: str) -> bool:
        raw = (type_repr or "").lower().strip()
        if not raw:
            return False

        if any(token in raw for token in ("int", "serial")):
            return True

        if raw.startswith("number(") or raw.startswith("numeric(") or raw.startswith("decimal("):
            match = re.search(r"\((\d+)(?:\s*,\s*(\d+))?\)", raw)
            if match is None:
                return False
            scale = match.group(2)
            return scale is None or int(scale) == 0

        return False

    @classmethod
    def _dtype_for_kind(
        cls,
        kind: ValueKind,
        *,
        type_repr: str = "",
        plan: ReadV3Plan | None = None,
        column: str | None = None,
    ) -> str:
        if kind == ValueKind.NUMERIC:
            if cls._is_integer_type_repr(type_repr):
                return "Int64"
            return "float64"
        if kind == ValueKind.BOOL:
            return "boolean"
        if kind in {ValueKind.DATE, ValueKind.DATETIME}:
            return pandas_datetime_dtype(plan.datetime_precision if plan is not None else None)
        if kind == ValueKind.STRING:
            return "string"
        if kind == ValueKind.UUID:
            return "string"
        if kind == ValueKind.JSON:
            return "object"
        source_context = ""
        if plan is not None:
            source_context = f", source={cls._source_name(plan)!r}"
        column_context = f", column={column!r}" if column is not None else ""
        type_context = f", type={type_repr!r}" if type_repr else ", type=''"
        raise ReadV3ExecutionError(
            "Strict read_v3 does not support output column kind. "
            f"kind={kind.value!r}{column_context}{type_context}{source_context}."
        )

    @classmethod
    def _dtype_for_column(cls, plan: ReadV3Plan, column: str) -> str:
        kind = plan.output_column_kinds.get(column, ValueKind.UNKNOWN)
        type_repr = plan.output_column_type_repr.get(column, "")
        return cls._dtype_for_kind(kind, type_repr=type_repr, plan=plan, column=column)

    @classmethod
    def _dtype_for_index(cls, plan: ReadV3Plan) -> Optional[str]:
        if plan.index_column_name == plan.hash_bucket_alias:
            return "int64"

        if plan.index_column_name == plan.partition_key_alias:
            if cls._uses_raw_mssql_partition_index(plan):
                return None
            return cls._dtype_for_kind(
                plan.partition_key_kind,
                type_repr=plan.partition_key_type_repr,
                plan=plan,
                column=plan.partition_key_name,
            )

        if plan.index_column_name in plan.output_columns:
            return cls._dtype_for_column(plan, plan.index_column_name)

        if plan.index_column_name == plan.partition_key_name:
            return cls._dtype_for_kind(
                plan.partition_key_kind,
                type_repr=plan.partition_key_type_repr,
                plan=plan,
                column=plan.partition_key_name,
            )

        return None

    @classmethod
    def _typed_empty_output(cls, plan: ReadV3Plan) -> pd.DataFrame:
        output = {
            column: pd.Series(dtype=cls._dtype_for_column(plan, column))
            for column in plan.output_columns
        }
        return pd.DataFrame(output)

    @classmethod
    def _restore_empty_output_schema(
        cls,
        df: pd.DataFrame,
        plan: ReadV3Plan,
    ) -> pd.DataFrame:
        if len(df.columns) == 0 and plan.output_columns:
            return cls._typed_empty_output(plan)
        return df

    @staticmethod
    def _normalize_datetime_series(series: pd.Series, target_dtype: str) -> pd.Series:
        parsed = pd.to_datetime(series, errors="raise", utc=True)
        if target_dtype in {"datetime64[ns]", "datetime64[us]", "datetime64[s]"}:
            return parsed.dt.tz_localize(None).astype(target_dtype)

        if target_dtype.startswith("datetime64[ns,") and target_dtype.endswith("]"):
            tz_name = target_dtype[len("datetime64[ns,") : -1].strip()
            if tz_name.upper() == "UTC":
                return parsed.astype("datetime64[ns, UTC]")
            return parsed.dt.tz_convert(tz_name).astype(target_dtype)

        return parsed.astype(target_dtype)

    @staticmethod
    def _normalize_boolean_series(series: pd.Series) -> pd.Series:
        def _coerce(value: object) -> object:
            if pd.isna(value):
                return pd.NA

            if isinstance(value, bool):
                return value

            if isinstance(value, int):
                if value in (0, 1):
                    return bool(value)
                raise ValueError(f"Integer value {value!r} is not valid for boolean cast")

            if isinstance(value, float):
                if value in (0.0, 1.0):
                    return bool(int(value))
                raise ValueError(f"Float value {value!r} is not valid for boolean cast")

            if isinstance(value, bytes):
                value = value.decode("utf-8")

            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"true", "t", "1", "yes", "y"}:
                    return True
                if normalized in {"false", "f", "0", "no", "n"}:
                    return False
                raise ValueError(f"String value {value!r} is not valid for boolean cast")

            raise ValueError(f"Unsupported value type {type(value).__name__!r} for boolean cast")

        normalized = series.map(_coerce)
        return normalized.astype("boolean")

    @classmethod
    def _normalize_string_series(
        cls,
        series: pd.Series,
        *,
        type_repr: str,
        dialect_name: str,
    ) -> pd.Series:
        if dialect_name == "mssql" and cls._is_mssql_binary_type_repr(type_repr):
            def _coerce(value: object) -> object:
                if pd.isna(value):
                    return pd.NA
                if isinstance(value, memoryview):
                    value = value.tobytes()
                if isinstance(value, (bytes, bytearray)):
                    return bytes(value).hex().upper()
                return str(value)

            return series.map(_coerce).astype("string")

        return series.astype("string")

    @classmethod
    def _apply_output_type_hints(
        cls,
        df: pd.DataFrame,
        plan: ReadV3Plan,
        *,
        stage: str,
        segment_label: str | None = None,
    ) -> pd.DataFrame:
        if not plan.output_column_kinds:
            return df

        for column in plan.output_columns:
            resolved_column = cls._resolve_column_name(df.columns, column)
            if resolved_column is None:
                continue
            target_dtype = cls._dtype_for_column(plan, column)
            try:
                if target_dtype.startswith("datetime64"):
                    df[resolved_column] = cls._normalize_datetime_series(df[resolved_column], target_dtype)
                elif target_dtype == "boolean":
                    df[resolved_column] = cls._normalize_boolean_series(df[resolved_column])
                elif target_dtype == "string":
                    df[resolved_column] = cls._normalize_string_series(
                        df[resolved_column],
                        type_repr=plan.output_column_type_repr.get(column, ""),
                        dialect_name=plan.dialect,
                    )
                elif target_dtype == "object":
                    df[resolved_column] = df[resolved_column].astype("object")
                else:
                    df[resolved_column] = df[resolved_column].astype(target_dtype)
            except (TypeError, ValueError) as exc:
                non_null_values = df[resolved_column].dropna().head(5).tolist()
                segment_ctx = f", segment={segment_label!r}" if segment_label else ""
                source_ctx = cls._source_name(plan)
                column_kind = plan.output_column_kinds.get(column, ValueKind.UNKNOWN).value
                column_type = plan.output_column_type_repr.get(column, "")
                raise ReadV3ExecutionError(
                    "Failed to cast read_v3 column "
                    f"{column!r} to dtype {target_dtype!r} at stage={stage!r}{segment_ctx}. "
                    f"source={source_ctx!r}, kind={column_kind!r}, type={column_type!r}, "
                    f"actual_dtype={str(df[resolved_column].dtype)!r}, sample_values={non_null_values!r}"
                ) from exc
        return df

    def load_partition(self, plan: ReadV3Plan, segment: ReadSegment) -> pd.DataFrame:
        sql = self._segment_sql(plan, segment)
        df = self._read_sql_bounded(sql, max_rows=plan.max_rows_per_partition)

        if df.empty:
            empty_df = self._typed_empty_output(plan)
            index_dtype = self._dtype_for_index(plan)
            if index_dtype:
                empty_df.index = pd.Index([], dtype=index_dtype, name=plan.index_column_name)
            else:
                empty_df.index = pd.Index([], name=plan.index_column_name)
            return empty_df

        df = self._apply_output_type_hints(
            df,
            plan,
            stage="load_partition",
            segment_label=segment.label,
        )

        index_col = self._pick_index_column(plan, df)
        df.index = df[index_col]

        if not df.index.is_monotonic_increasing:
            raise ReadV3ExecutionError(
                f"Segment index is not monotonic increasing for segment={segment.label!r}"
            )

        self._validate_index_bounds(df, segment)
        return self._finalize_output(df, plan)

    def build_meta(self, plan: ReadV3Plan) -> pd.DataFrame:
        output_select = ", ".join(
            plan.output_column_select_exprs.get(
                column,
                self.dialect.quote_result_column(plan.output_column_sql_names.get(column, column)),
            )
            for column in plan.output_columns
        )
        sample_sql = self._wrap_sql(
            plan,
            f"SELECT {output_select} {plan.relation_sql}",
        )
        sample_sql = self.dialect.cap_rows_sql(sample_sql, 1)
        sample_df = self.sql_runner.query_df(sample_sql)

        if sample_df.empty:
            sql = self._wrap_sql(
                plan,
                f"SELECT {output_select} {plan.relation_sql} WHERE 1=0",
            )
            df = self.sql_runner.query_df(sql)
            df = self._restore_empty_output_schema(df, plan)
            df = self._apply_output_type_hints(df, plan, stage="build_meta_empty")
        else:
            df = self._apply_output_type_hints(sample_df.head(0).copy(), plan, stage="build_meta_sample")
        df = self._project_output_columns(df, plan)

        index_dtype = self._dtype_for_index(plan)
        if index_dtype:
            meta_index = pd.Index([], dtype=index_dtype, name=plan.index_column_name)
        else:
            meta_index = pd.Index([], name=plan.index_column_name)
        df.index = meta_index
        return df
