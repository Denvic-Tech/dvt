import contextlib
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Literal, cast

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator
from sqlalchemy import Engine, Row, create_engine, inspect as sa_inspect

from core.db.connect.sqlalchemy_url import with_database
from core.db.read_v3.dialects import resolve_dialect
from core.db.read_v3.query_metadata import describe_query_columns

from src.constants import UNSET
from src.node_dsl import IO, BaseNode, InputField, NodeValidationError, OutputField
from src.node_dsl.connection_types import SqlConnectionRecord
from src.node_dsl.core.input_values import resolve_node_input_value
from src.node_dsl.hooks import on_validation
from src.node_dsl.node_mixins.sql import SQLCodeInputFieldMixin
from src.node_dsl.runtime.connections import resolve_sql_dialect_name, resolve_sql_engine
from src.node_dsl.variables import (
    VariableOutput,
    apply_nullable_default_policy,
    coerce_variable_value,
    is_unresolved_value,
    resolve_literal_input_value,
)
from src.node_dsl.variables.type_system import (
    ensure_list_supported_variable_type,
    infer_list_item_variable_type_from_value,
    infer_variable_scalar_type_from_metadata_type,
    infer_variable_scalar_type_from_value,
    normalize_variable_list_items,
    normalize_variable_scalar_type,
)
from src.node_dsl.variables.types import VariableType

ReadVariablesMode = Literal["manual", "sql"]
AggregationFunction = Literal["min", "max", "count", "count_distinct", "sum", "avg", "first", "last"]

_MANUAL_AGGREGATIONS: tuple[str, ...] = (
    "min",
    "max",
    "count",
    "count_distinct",
    "sum",
    "avg",
    "first",
    "last",
)
_ORDERED_AGGREGATIONS_REQUIRING_ORDER_BY = frozenset({"first", "last"})
_SUPPORTED_AGGREGATIONS_BY_DIALECT: dict[str, list[str]] = {
    "postgresql": list(_MANUAL_AGGREGATIONS),
    "mysql": list(_MANUAL_AGGREGATIONS),
    "mssql": list(_MANUAL_AGGREGATIONS),
    "oracle": list(_MANUAL_AGGREGATIONS),
    "clickhouse": list(_MANUAL_AGGREGATIONS),
    "sqlite": list(_MANUAL_AGGREGATIONS),
}
_BOOL_ADAPTER = TypeAdapter(bool)


class VariableValuePolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nullable: bool = Field(default=False)
    default: Any = Field(default=None)
    target_dtype: VariableType | None = Field(default=None)
    is_list_type: bool = Field(default=False)

    @property
    def default_is_set(self) -> bool:
        return "default" in self.model_fields_set

    @property
    def resolved_target_dtype(self) -> VariableType | None:
        if self.target_dtype is None:
            return None
        if self.is_list_type:
            return ensure_list_supported_variable_type(self.target_dtype)
        return normalize_variable_scalar_type(self.target_dtype)

    @model_validator(mode="after")
    def _validate_default_literal(self) -> "VariableValuePolicyModel":
        if self.default_is_set:
            resolve_literal_input_value(self.default, field_name="default")
        return self


class VariableConfiguration(VariableValuePolicyModel):
    database_name: str | None = Field(default=None)
    schema_name: str | None = Field(default=None)
    table_name: str
    column_name: str
    aggregation: AggregationFunction
    order_by_column: str | None = Field(default=None)

    @model_validator(mode="after")
    def _validate_shape(self) -> "VariableConfiguration":
        if self.aggregation in _ORDERED_AGGREGATIONS_REQUIRING_ORDER_BY and not self.order_by_column:
            raise ValueError(
                f"Aggregation '{self.aggregation}' requires non-empty 'order_by_column'."
            )
        if self.aggregation not in _MANUAL_AGGREGATIONS:
            raise ValueError(f"Unsupported aggregation '{self.aggregation}'.")
        return self


class SqlVariableConfiguration(VariableValuePolicyModel):
    pass


_MANUAL_VARIABLES_ADAPTER = TypeAdapter(dict[str, VariableConfiguration])
_SQL_VARIABLES_ADAPTER = TypeAdapter(dict[str, SqlVariableConfiguration])


def _build_additional_schema() -> dict[str, Any]:
    return {
        "read_variables_from_db": {
            "version": 3,
            "modes": ["manual", "sql"],
            "null_policy": {
                "default_must_be_literal": True,
                "default_applied_when_value_is_null": True,
                "nullable_keeps_null_when_default_missing": True,
                "fail_fast_when_null_without_policy": True,
            },
            "manual_mode": {
                "aggregations_by_dialect": _SUPPORTED_AGGREGATIONS_BY_DIALECT,
                "order_by_required_for": sorted(_ORDERED_AGGREGATIONS_REQUIRING_ORDER_BY),
                "target_dtype_override_supported": True,
                "list_type_supported": True,
            },
            "sql_mode": {
                "must_return_at_most_one_row": True,
                "zero_rows_allowed_with_defaults_or_nullable": True,
                "duplicate_columns_forbidden": True,
                "requires_at_least_one_column": True,
                "per_column_overrides_supported": True,
                "target_dtype_override_supported": True,
                "list_type_supported": True,
            },
        }
    }


def _build_manual_variables_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "propertyNames": {"type": "string"},
        "additionalProperties": VariableConfiguration.model_json_schema(),
    }


def _build_sql_variables_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "propertyNames": {"type": "string"},
        "additionalProperties": SqlVariableConfiguration.model_json_schema(),
    }


def _model_payload_to_dict(payload: BaseModel) -> dict[str, Any]:
    return payload.model_dump(exclude_unset=True)


def _is_null_like(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except Exception:
        return False


def _normalize_scalar_value(value: Any) -> Any:
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


def _normalize_list_value(value: Any) -> list[Any] | None:
    if _is_null_like(value):
        return None

    normalized_value = _normalize_scalar_value(value)
    return normalize_variable_list_items(normalized_value, parse_json_strings=True)


def _coerce_output_value(
    value: Any,
    *,
    target_dtype: VariableType | None,
    is_list_type: bool = False,
) -> Any:
    normalized_value = _normalize_scalar_value(value)
    if target_dtype is None:
        if is_list_type:
            return _normalize_list_value(normalized_value)
        return normalized_value
    return coerce_variable_value(
        normalized_value,
        target_dtype,
        allow_none=True,
        is_list_type=is_list_type,
        parse_json_strings=is_list_type,
    )


def _infer_variable_type(value: Any) -> VariableType:
    return infer_variable_scalar_type_from_value(_normalize_scalar_value(value))


def _infer_list_variable_type(value: Any) -> VariableType:
    normalized_items = _normalize_list_value(value)
    if normalized_items is None:
        raise ValueError("Cannot infer list item type from null value.")
    return infer_list_item_variable_type_from_value(normalized_items)


def _duplicate_columns(columns: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    for column_name in columns:
        counts[column_name] = counts.get(column_name, 0) + 1
    return sorted(column_name for column_name, count in counts.items() if count > 1)


def _normalize_column_name(name: object) -> str:
    return str(name).strip().strip("[]`\"").lower()


class ReadVariablesFromDB(
    SQLCodeInputFieldMixin,
    BaseNode
):
    TITLE = "Read Variables DB"
    EMOJI = "🧮"
    CATEGORY = "Extraction"
    CACHABLE = False
    ADDITIONAL_SCHEMA = _build_additional_schema()
    METADATA_VARIABLE_PREPASS_INPUTS = frozenset({"manual_variables", "sql_query", "sql_variables"})
    ALLOW_NULLABLE_SQL_CODE = True

    connection: SqlConnectionRecord | Engine = InputField()
    mode: ReadVariablesMode = InputField(default="manual")

    sql_code: str | None = InputField(
        default=None,
        multiline=True,
        expression_policy="default",
        sql_template=True,
    )

    manual_variables: dict[str, VariableConfiguration] = InputField(
        default={},
        description="Manual variable definitions grouped by output variable name.",
        use_connection=False,
    )
    sql_variables: dict[str, SqlVariableConfiguration] = InputField(
        default={},
        description="Per-column NULL/default overrides for `sql` mode.",
        use_connection=False,
    )

    output_variables: dict[str, IO.VARIABLE] = OutputField(
        description="Output variables",
        force_handle_visible=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._engine_cache: dict[str | None, Engine] = {}

    def _runtime_variables(self) -> dict[str, Any]:
        runtime_variables: dict[str, Any] = {}
        project_variables = self.project_variables
        if project_variables is not None:
            runtime_variables.update(project_variables.raw_values)
        if isinstance(self.input_variables, dict):
            runtime_variables.update(self.input_variables)
        return runtime_variables

    def _resolve_input_value(self, value: Any, *, target_type: Any) -> Any:
        resolved_value = resolve_node_input_value(
            value,
            variables=self._runtime_variables(),
            target_type=target_type,
            allow_expressions=True,
            expression_policy="default",
            allow_unresolved=False,
        )
        if is_unresolved_value(resolved_value):
            raise NodeValidationError(
                f"Could not resolve input value for ReadVariablesFromDB: {resolved_value.reason}"
            )
        return resolved_value

    @staticmethod
    def _resolve_literal_bool(value: Any, *, field_name: str) -> bool:
        literal_value = resolve_literal_input_value(value, field_name=field_name)
        return _BOOL_ADAPTER.validate_python(literal_value)

    @staticmethod
    def _resolve_literal_default(value: Any) -> Any:
        return resolve_literal_input_value(value, field_name="default")

    def _normalize_mode(self) -> ReadVariablesMode:
        resolved_mode = self._resolve_input_value(self.mode, target_type=str)
        if resolved_mode not in {"manual", "sql"}:
            raise NodeValidationError(f"Unsupported mode '{resolved_mode}'.")
        return cast(ReadVariablesMode, resolved_mode)

    def should_validate_sql_code(self) -> bool:
        return self._normalize_mode() == "sql"

    def _normalize_sql_query(self) -> str:
        raw_query = self._resolve_input_value(self.sql_code, target_type=str)
        if not isinstance(raw_query, str) or not raw_query.strip():
            raise NodeValidationError("`sql_query` must be a non-empty string in `sql` mode.")
        return raw_query.strip().rstrip(";")

    def _normalize_manual_variables(self) -> dict[str, VariableConfiguration]:
        raw_manual_variables = self.manual_variables or {}
        if not isinstance(raw_manual_variables, dict):
            raise NodeValidationError("`manual_variables` must be a dictionary.")

        resolved_configurations: dict[str, dict[str, Any]] = {}
        for variable_name, payload in raw_manual_variables.items():
            if not isinstance(variable_name, str) or not variable_name.strip():
                raise NodeValidationError("Manual variable names must be non-empty strings.")

            if isinstance(payload, VariableConfiguration):
                payload_dict = _model_payload_to_dict(payload)
            elif isinstance(payload, dict):
                payload_dict = dict(payload)
            else:
                raise NodeValidationError(
                    f"Variable '{variable_name}' must be configured as an object."
                )

            resolved_payload: dict[str, Any] = {
                "database_name": self._resolve_input_value(
                    payload_dict.get("database_name"), target_type=str | None
                ),
                "schema_name": self._resolve_input_value(
                    payload_dict.get("schema_name"), target_type=str | None
                ),
                "table_name": self._resolve_input_value(payload_dict.get("table_name"), target_type=str),
                "column_name": self._resolve_input_value(
                    payload_dict.get("column_name"), target_type=str
                ),
                "aggregation": self._resolve_input_value(
                    payload_dict.get("aggregation"), target_type=str
                ),
                "order_by_column": self._resolve_input_value(
                    payload_dict.get("order_by_column"), target_type=str | None
                ),
                "target_dtype": self._resolve_input_value(
                    payload_dict.get("target_dtype"), target_type=str | None
                ),
            }

            if "nullable" in payload_dict:
                resolved_payload["nullable"] = self._resolve_literal_bool(
                    payload_dict["nullable"],
                    field_name="nullable",
                )
            if "default" in payload_dict:
                resolved_payload["default"] = self._resolve_literal_default(payload_dict["default"])
            if "is_list_type" in payload_dict:
                resolved_payload["is_list_type"] = self._resolve_literal_bool(
                    payload_dict["is_list_type"],
                    field_name="is_list_type",
                )
            if "target_dtype" in payload_dict:
                resolved_payload["target_dtype"] = self._resolve_input_value(
                    payload_dict["target_dtype"],
                    target_type=str | None,
                )

            resolved_configurations[variable_name] = resolved_payload

        if not resolved_configurations:
            raise NodeValidationError(
                "`manual_variables` must contain at least one variable in `manual` mode."
            )

        try:
            return _MANUAL_VARIABLES_ADAPTER.validate_python(resolved_configurations)
        except ValidationError as exc:
            raise NodeValidationError(f"Invalid `manual_variables`: {exc}") from exc

    def _normalize_sql_variables(self) -> dict[str, SqlVariableConfiguration]:
        raw_sql_variables = self.sql_variables or {}
        if not isinstance(raw_sql_variables, dict):
            raise NodeValidationError("`sql_variables` must be a dictionary.")

        resolved_configurations: dict[str, dict[str, Any]] = {}
        for variable_name, payload in raw_sql_variables.items():
            if not isinstance(variable_name, str) or not variable_name.strip():
                raise NodeValidationError("SQL variable names must be non-empty strings.")

            if isinstance(payload, SqlVariableConfiguration):
                payload_dict = _model_payload_to_dict(payload)
            elif isinstance(payload, dict):
                payload_dict = dict(payload)
            else:
                raise NodeValidationError(
                    f"SQL variable override '{variable_name}' must be configured as an object."
                )

            resolved_payload: dict[str, Any] = {}
            if "nullable" in payload_dict:
                resolved_payload["nullable"] = self._resolve_literal_bool(
                    payload_dict["nullable"],
                    field_name="nullable",
                )
            if "default" in payload_dict:
                resolved_payload["default"] = self._resolve_literal_default(payload_dict["default"])
            if "is_list_type" in payload_dict:
                resolved_payload["is_list_type"] = self._resolve_literal_bool(
                    payload_dict["is_list_type"],
                    field_name="is_list_type",
                )
            if "target_dtype" in payload_dict:
                resolved_payload["target_dtype"] = self._resolve_input_value(
                    payload_dict["target_dtype"],
                    target_type=str | None,
                )

            resolved_configurations[variable_name] = resolved_payload

        try:
            return _SQL_VARIABLES_ADAPTER.validate_python(resolved_configurations)
        except ValidationError as exc:
            raise NodeValidationError(f"Invalid `sql_variables`: {exc}") from exc

    def _validate_dialect_aggregation_support(
        self,
        *,
        dialect_name: str,
        configuration: VariableConfiguration,
        variable_name: str,
    ) -> None:
        supported_aggregations = _SUPPORTED_AGGREGATIONS_BY_DIALECT.get(dialect_name)
        if supported_aggregations is None:
            raise NodeValidationError(f"Unsupported SQL dialect '{dialect_name}'.")
        if configuration.aggregation not in supported_aggregations:
            raise NodeValidationError(
                f"Aggregation '{configuration.aggregation}' is not supported for "
                f"dialect '{dialect_name}' in variable '{variable_name}'."
            )

    def _get_engine(self, database_name: str | None) -> Engine:
        cache_key = database_name or None
        cached_engine = self._engine_cache.get(cache_key)
        if cached_engine is not None:
            return cached_engine

        base_engine = resolve_sql_engine(self.connection)
        if not database_name:
            engine = base_engine
        else:
            url = base_engine.url
            if url.get_backend_name().lower().startswith("oracle"):
                engine = base_engine
            else:
                engine = create_engine(with_database(url, database_name))

        self._engine_cache[cache_key] = engine
        return engine

    @staticmethod
    def _build_table_sql(configuration: VariableConfiguration, dialect) -> str:
        return dialect.full_table_name(
            table=configuration.table_name,
            schema=configuration.schema_name,
        )

    @staticmethod
    def _build_manual_query(configuration: VariableConfiguration, dialect) -> str:
        table_sql = ReadVariablesFromDB._build_table_sql(configuration, dialect)
        column_sql = dialect.quote_ident(configuration.column_name)

        if configuration.aggregation == "min":
            return f"SELECT MIN({column_sql}) AS value FROM {table_sql}"
        if configuration.aggregation == "max":
            return f"SELECT MAX({column_sql}) AS value FROM {table_sql}"
        if configuration.aggregation == "count":
            return f"SELECT COUNT({column_sql}) AS value FROM {table_sql}"
        if configuration.aggregation == "count_distinct":
            return f"SELECT COUNT(DISTINCT {column_sql}) AS value FROM {table_sql}"
        if configuration.aggregation == "sum":
            return f"SELECT SUM({column_sql}) AS value FROM {table_sql}"
        if configuration.aggregation == "avg":
            return f"SELECT AVG({column_sql}) AS value FROM {table_sql}"

        order_by_sql = dialect.quote_ident(configuration.order_by_column or "")
        direction = "ASC" if configuration.aggregation == "first" else "DESC"
        return (
            f"SELECT {column_sql} AS value "
            f"FROM {table_sql} "
            f"ORDER BY {order_by_sql} {direction} "
            f"{dialect.limit_offset(1, 0)}"
        )

    @staticmethod
    def _execute_preview_query(
        *,
        engine: Engine,
        sql_query: str,
        context: str,
    ) -> tuple[list[str], Sequence[Row[Any]]]:
        with engine.connect() as conn:
            result = conn.exec_driver_sql(sql_query)
            column_names = [str(column_name) for column_name in result.keys()]
            rows = result.fetchmany(2)

        if not column_names:
            raise ValueError(f"{context}: query must return at least one column.")

        duplicate_columns = _duplicate_columns(column_names)
        if duplicate_columns:
            raise ValueError(
                f"{context}: query returned duplicate column names: {duplicate_columns}"
            )

        return column_names, rows

    @staticmethod
    def _resolve_output_variable_type(
        value: Any,
        *,
        fallback_type: VariableType | None,
        target_dtype: VariableType | None,
        is_list_type: bool = False,
        prefer_fallback_type: bool = False,
    ) -> VariableType:
        if target_dtype is not None:
            return target_dtype
        if prefer_fallback_type and not is_list_type and fallback_type is not None:
            return fallback_type
        if value is not None:
            if is_list_type:
                return _infer_list_variable_type(value)
            return _infer_variable_type(value)
        if is_list_type and fallback_type is not None:
            return ensure_list_supported_variable_type(fallback_type)
        return fallback_type or IO.JSON

    def _build_variable_output(
        self,
        *,
        name: str,
        raw_value: Any,
        fallback_type: VariableType | None,
        policy: VariableValuePolicyModel,
        prefer_fallback_type: bool = False,
    ) -> VariableOutput:
        target_dtype = policy.resolved_target_dtype
        normalized_value = _coerce_output_value(
            raw_value,
            target_dtype=target_dtype,
            is_list_type=policy.is_list_type,
        )
        resolved_value = apply_nullable_default_policy(
            normalized_value,
            nullable=policy.nullable,
            default_value=policy.default if policy.default_is_set else UNSET,
            default_resolver=lambda literal: _coerce_output_value(
                literal,
                target_dtype=target_dtype,
                is_list_type=policy.is_list_type,
            ),
            null_error_message=(
                f"Variable '{name}' resolved to NULL. Configure `default` or set `nullable=true`."
            ),
        )
        if (
            policy.is_list_type
            and target_dtype is None
            and resolved_value is None
            and fallback_type is None
        ):
            raise ValueError(
                f"Variable '{name}' cannot determine list item type from NULL value. "
                "Set `target_dtype` explicitly."
            )
        variable_type = self._resolve_output_variable_type(
            resolved_value,
            fallback_type=fallback_type,
            target_dtype=target_dtype,
            is_list_type=policy.is_list_type,
            prefer_fallback_type=prefer_fallback_type,
        )
        return VariableOutput(
            name=name,
            type=variable_type,
            value=resolved_value,
            var_type="user",
            is_list_type=policy.is_list_type,
        )

    @staticmethod
    def _get_column_type_from_schema(
        *,
        engine: Engine,
        schema_name: str | None,
        table_name: str,
        column_name: str,
    ) -> VariableType | None:
        try:
            inspector = sa_inspect(engine)
            for column in inspector.get_columns(table_name, schema=schema_name):
                if str(column.get("name")) == column_name:
                    return infer_variable_scalar_type_from_metadata_type(column.get("type"))
        except Exception:
            return None
        return None

    @staticmethod
    def _get_query_column_types(
        *,
        engine: Engine,
        raw_query: str,
        column_names: list[str],
    ) -> dict[str, VariableType | None]:
        column_types: dict[str, VariableType | None] = dict.fromkeys(column_names)
        normalized_column_names = {
            _normalize_column_name(column_name): column_name for column_name in column_names
        }
        for column_name, type_repr in describe_query_columns(engine, raw_query):
            resolved_column_name = normalized_column_names.get(_normalize_column_name(column_name))
            if resolved_column_name is not None:
                column_types[resolved_column_name] = infer_variable_scalar_type_from_metadata_type(
                    type_repr
                )
        return column_types

    def _read_manual_mode(self) -> dict[str, VariableOutput]:
        normalized_manual_variables = self._normalize_manual_variables()
        self.manual_variables = normalized_manual_variables

        outputs: dict[str, VariableOutput] = {}
        value_cache: dict[tuple[Any, ...], Any] = {}
        type_cache: dict[tuple[Any, ...], VariableType | None] = {}

        for variable_name, configuration in normalized_manual_variables.items():
            engine = self._get_engine(configuration.database_name)
            dialect = resolve_dialect(engine)
            self._validate_dialect_aggregation_support(
                dialect_name=dialect.name,
                configuration=configuration,
                variable_name=variable_name,
            )

            cache_key = (
                configuration.database_name,
                configuration.schema_name,
                configuration.table_name,
                configuration.column_name,
                configuration.aggregation,
                configuration.order_by_column,
            )
            if cache_key not in value_cache:
                sql_query = self._build_manual_query(configuration, dialect)
                _, rows = self._execute_preview_query(
                    engine=engine,
                    sql_query=sql_query,
                    context=f"Variable '{variable_name}'",
                )
                if len(rows) > 1:
                    raise ValueError(f"Variable '{variable_name}': query returned more than 1 row.")
                value_cache[cache_key] = rows[0][0] if rows else None

            if cache_key not in type_cache:
                type_cache[cache_key] = self._get_column_type_from_schema(
                    engine=engine,
                    schema_name=configuration.schema_name,
                    table_name=configuration.table_name,
                    column_name=configuration.column_name,
                )

            outputs[variable_name] = self._build_variable_output(
                name=variable_name,
                raw_value=value_cache[cache_key],
                fallback_type=type_cache[cache_key],
                policy=configuration,
            )

        return outputs

    def _read_sql_mode(self) -> dict[str, VariableOutput]:
        normalized_query = self._normalize_sql_query()
        normalized_sql_variables = self._normalize_sql_variables()
        self.sql_code = normalized_query
        self.sql_variables = normalized_sql_variables

        engine = self._get_engine(None)
        column_names, rows = self._execute_preview_query(
            engine=engine,
            sql_query=normalized_query,
            context="`sql_query`",
        )

        if len(rows) > 1:
            raise ValueError("`sql_query`: query returned more than 1 row.")

        column_name_by_normalized = {
            _normalize_column_name(column_name): column_name for column_name in column_names
        }
        resolved_sql_variables: dict[str, SqlVariableConfiguration] = {}
        duplicate_override_columns: set[str] = set()
        unknown_overrides: list[str] = []
        for variable_name, policy in normalized_sql_variables.items():
            resolved_column_name = column_name_by_normalized.get(_normalize_column_name(variable_name))
            if resolved_column_name is None:
                unknown_overrides.append(variable_name)
                continue
            if resolved_column_name in resolved_sql_variables:
                duplicate_override_columns.add(resolved_column_name)
                continue
            resolved_sql_variables[resolved_column_name] = policy
        if duplicate_override_columns:
            raise ValueError(
                "`sql_variables` contains duplicate overrides for normalized columns: "
                f"{sorted(duplicate_override_columns)}"
            )
        if unknown_overrides:
            raise ValueError(
                "`sql_variables` contains overrides for columns that are not returned by "
                f"`sql_query`: {sorted(unknown_overrides)}"
            )

        column_types = self._get_query_column_types(
            engine=engine,
            raw_query=normalized_query,
            column_names=column_names,
        )
        row = rows[0] if rows else None

        outputs: dict[str, VariableOutput] = {}
        for index, column_name in enumerate(column_names):
            if not column_name.strip():
                raise ValueError("`sql_query` returned an empty column name.")
            policy = resolved_sql_variables.get(column_name, SqlVariableConfiguration())
            raw_value = row[index] if row is not None else None
            outputs[column_name] = self._build_variable_output(
                name=column_name,
                raw_value=raw_value,
                fallback_type=column_types.get(column_name),
                policy=policy,
                prefer_fallback_type=True,
            )

        return outputs

    def _execute(self) -> None:
        mode = self._normalize_mode()
        self.mode = mode

        if mode == "manual":
            self.output_variables = self._read_manual_mode()
            return

        self.output_variables = self._read_sql_mode()

    @on_validation
    def validate_configuration(self) -> None:
        mode = self._normalize_mode()
        self.mode = mode
        if mode == "manual":
            self.manual_variables = self._normalize_manual_variables()
            return
        self.sql_code = self._normalize_sql_query()
        self.sql_variables = self._normalize_sql_variables()

    def get_dialect_name_for_sql_code_metadata(self) -> str | None:
        return resolve_sql_dialect_name(self.connection)

    def process(self) -> None:
        self._execute()

    def process_metadata(self) -> None:
        self._execute()


ReadVariablesFromDB._input_field_instances["manual_variables"].schema = _build_manual_variables_schema()
ReadVariablesFromDB._input_field_instances["sql_variables"].schema = _build_sql_variables_schema()
