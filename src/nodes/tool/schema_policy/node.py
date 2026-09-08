from dataclasses import dataclass
from typing import Any, Literal

import dask.dataframe as dd
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.types import DataType

from src.modules.data_catalog import ColumnSchema, TableSchema
from src.node_dsl import DFOutputBaseNode, InputField, NodeValidationError, OutputField

MissingColumnAction = Literal["error", "fill", "ignore"]
TypeMismatchAction = Literal["error", "cast", "soft_cast", "ignore"]
ExtraColumnsAction = Literal["error", "drop", "ignore"]


class ColumnSchemaPolicy(BaseModel):
    """Политика применения одной колонки из TableSchema к DataFrame."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    on_missing: MissingColumnAction = Field(
        default="error",
        description="Что делать, если колонка из Schema отсутствует в DataFrame.",
    )
    fill_value: Any = Field(
        default=None,
        description="Константа для заполнения отсутствующей колонки при on_missing='fill'.",
    )
    on_type_mismatch: TypeMismatchAction = Field(
        default="error",
        description="Что делать, если dtype DataFrame не соответствует dtype из Schema.",
    )


class SchemaPolicySettings(BaseModel):
    """Настройки Schema Policy для всех колонок схемы и лишних колонок DataFrame."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    columns: dict[str, ColumnSchemaPolicy] = Field(
        description="Политики, заданные по имени каждой колонки из Schema.",
    )
    on_extra_columns: ExtraColumnsAction = Field(
        default="error",
        description="Что делать с колонками DataFrame, которых нет в Schema.",
    )


@dataclass(frozen=True, slots=True)
class _ColumnExecutionRule:
    name: str
    target_type: DataType | None
    add_missing: bool = False
    fill_value: Any = None
    cast_mode: Literal["cast", "soft_cast"] | None = None

    def __dask_tokenize__(self) -> tuple[Any, ...]:
        return (
            type(self).__name__,
            self.name,
            self.target_type,
            self.add_missing,
            self.fill_value,
            self.cast_mode,
        )


def _schema_data_type(column: ColumnSchema) -> DataType | None:
    if column.dtype is None:
        return None
    return DataType.from_type(column.dtype)


def _is_type_compatible(actual: DataType, expected: DataType) -> bool:
    # OBJECT is intentionally generic. DICTIONARY is physically represented by object dtype
    # in pandas, so dtype metadata alone cannot distinguish it from arbitrary Python objects.
    if expected is DataType.OBJECT:
        return True
    if expected is DataType.DICTIONARY and actual is DataType.OBJECT:
        return True
    return actual is expected


def _strict_cast_series(series: pd.Series, target_type: DataType) -> pd.Series:
    if target_type is DataType.INT:
        numeric = pd.to_numeric(series, errors="raise")
        non_null = numeric.dropna()
        if not non_null.empty and not (non_null % 1 == 0).all():
            raise ValueError("fractional values cannot be cast to integer without data loss")
        return numeric.astype("Int64")

    if target_type is DataType.FLOAT:
        return pd.to_numeric(series, errors="raise").astype("float64")

    if target_type is DataType.STRING:
        return series.astype("string")

    if target_type is DataType.BOOLEAN:
        return series.astype("boolean")

    if target_type is DataType.DATETIME:
        return pd.to_datetime(series, errors="raise")

    if target_type is DataType.TIMEDELTA:
        return pd.to_timedelta(series, errors="raise")

    if target_type is DataType.CATEGORY:
        return series.astype("category")

    if target_type is DataType.DICTIONARY:
        invalid = series.notna() & ~series.map(lambda value: isinstance(value, dict))
        if bool(invalid.any()):
            raise ValueError("non-dictionary values cannot be cast to DICTIONARY")
        return series.astype("object")

    if target_type is DataType.OBJECT:
        return series.astype("object")

    raise ValueError(f"Unsupported target dtype: {target_type.value}")


def _soft_cast_boolean(series: pd.Series) -> pd.Series:
    normalized = series.astype("string").str.strip().str.lower()
    values = normalized.map(
        {
            "true": True,
            "1": True,
            "yes": True,
            "y": True,
            "false": False,
            "0": False,
            "no": False,
            "n": False,
        }
    )
    return values.astype("boolean")


def _soft_cast_series(series: pd.Series, target_type: DataType) -> pd.Series:
    if target_type is DataType.INT:
        numeric = pd.to_numeric(series, errors="coerce")
        integral = numeric.isna() | (numeric % 1 == 0)
        return numeric.where(integral).astype("Int64")

    if target_type is DataType.FLOAT:
        return pd.to_numeric(series, errors="coerce").astype("float64")

    if target_type is DataType.STRING:
        return series.astype("string")

    if target_type is DataType.BOOLEAN:
        return _soft_cast_boolean(series)

    if target_type is DataType.DATETIME:
        return pd.to_datetime(series, errors="coerce")

    if target_type is DataType.TIMEDELTA:
        return pd.to_timedelta(series, errors="coerce")

    if target_type is DataType.CATEGORY:
        return series.astype("category")

    if target_type is DataType.DICTIONARY:
        return series.where(series.map(lambda value: value is None or isinstance(value, dict)))

    if target_type is DataType.OBJECT:
        return series.astype("object")

    raise ValueError(f"Unsupported target dtype: {target_type.value}")


def _constant_series(index: pd.Index, value: Any) -> pd.Series:
    return pd.Series([value] * len(index), index=index)


def _apply_schema_policy_partition(
    dataframe: pd.DataFrame,
    *,
    drop_columns: tuple[str, ...],
    rules: tuple[_ColumnExecutionRule, ...],
) -> pd.DataFrame:
    output = dataframe.drop(columns=list(drop_columns), errors="ignore").copy()

    for rule in rules:
        if rule.add_missing:
            output[rule.name] = _constant_series(output.index, rule.fill_value)
            if rule.target_type is not None:
                try:
                    output[rule.name] = _strict_cast_series(output[rule.name], rule.target_type)
                except Exception as exc:
                    raise ValueError(
                        f"Schema Policy cannot fill column '{rule.name}' with value "
                        f"{rule.fill_value!r} as {rule.target_type.value}."
                    ) from exc
            continue

        if rule.cast_mode is None or rule.target_type is None:
            continue

        try:
            if rule.cast_mode == "cast":
                output[rule.name] = _strict_cast_series(output[rule.name], rule.target_type)
            else:
                output[rule.name] = _soft_cast_series(output[rule.name], rule.target_type)
        except Exception as exc:
            raise ValueError(
                f"Schema Policy failed to {rule.cast_mode} column '{rule.name}' "
                f"to {rule.target_type.value}."
            ) from exc

    return output


class SchemaPolicy(DFOutputBaseNode):
    """Применяет к Dask DataFrame политики соответствия TableSchema."""

    TITLE = "Schema Policy"
    CATEGORY = "Tool"

    df: dd.DataFrame = InputField()
    schema: TableSchema = InputField()
    policy: SchemaPolicySettings = InputField()

    output: dd.DataFrame = OutputField()

    @staticmethod
    def _normalize_policy(value: SchemaPolicySettings | dict[str, Any]) -> SchemaPolicySettings:
        if isinstance(value, SchemaPolicySettings):
            return value
        try:
            return SchemaPolicySettings.model_validate(value)
        except ValidationError as exc:
            raise NodeValidationError(f"Invalid Schema Policy settings: {exc}") from exc

    def _validate_policy_columns(self, policy: SchemaPolicySettings) -> None:
        schema_names = {column.name for column in self.schema.columns}
        policy_names = set(policy.columns)

        missing_policy = sorted(schema_names - policy_names)
        unknown_policy = sorted(policy_names - schema_names)
        if missing_policy:
            raise NodeValidationError(
                f"Schema Policy is not configured for schema columns: {missing_policy!r}."
            )
        if unknown_policy:
            raise NodeValidationError(
                f"Schema Policy contains columns that are absent from Schema: {unknown_policy!r}."
            )

    def _validate_dataframe_columns(self) -> None:
        dataframe_columns = list(self.df.columns)
        duplicates = sorted(
            {name for name in dataframe_columns if dataframe_columns.count(name) > 1}
        )
        if duplicates:
            raise NodeValidationError(
                f"Schema Policy does not support duplicated DataFrame columns: {duplicates!r}."
            )

    @staticmethod
    def _validate_supported_type(
        column: ColumnSchema,
        column_policy: ColumnSchemaPolicy,
    ) -> DataType | None:
        target_type = _schema_data_type(column)
        if target_type is not DataType.UNKNOWN:
            return target_type

        if column_policy.on_type_mismatch == "ignore":
            return None
        raise NodeValidationError(
            f"Schema column '{column.name}' has unsupported dtype {column.dtype!r}; "
            "set on_type_mismatch='ignore' or use a supported dtype."
        )

    @staticmethod
    def _validate_fill_value(
        *,
        column: ColumnSchema,
        target_type: DataType | None,
        value: Any,
    ) -> None:
        if target_type is None:
            return
        try:
            _strict_cast_series(pd.Series([value], name=column.name), target_type)
        except Exception as exc:
            raise NodeValidationError(
                f"Schema Policy fill_value={value!r} for column '{column.name}' "
                f"cannot be cast to {target_type.value}."
            ) from exc

    def _build_execution_plan(
        self,
        policy: SchemaPolicySettings,
    ) -> tuple[tuple[str, ...], tuple[_ColumnExecutionRule, ...]]:
        self._validate_dataframe_columns()
        self._validate_policy_columns(policy)

        schema_names = {column.name for column in self.schema.columns}
        dataframe_names = set(self.df.columns)
        extra_columns = tuple(name for name in self.df.columns if name not in schema_names)

        if extra_columns and policy.on_extra_columns == "error":
            raise NodeValidationError(
                f"DataFrame contains columns that are absent from Schema: {list(extra_columns)!r}."
            )
        drop_columns = extra_columns if policy.on_extra_columns == "drop" else ()

        actual_dtypes = self.df.dtypes.to_dict()
        rules: list[_ColumnExecutionRule] = []

        for column in self.schema.columns:
            column_policy = policy.columns[column.name]
            target_type = self._validate_supported_type(column, column_policy)

            if column.name not in dataframe_names:
                match column_policy.on_missing:
                    case "error":
                        raise NodeValidationError(
                            f"DataFrame is missing schema column '{column.name}'."
                        )
                    case "ignore":
                        continue
                    case "fill":
                        self._validate_fill_value(
                            column=column,
                            target_type=target_type,
                            value=column_policy.fill_value,
                        )
                        rules.append(
                            _ColumnExecutionRule(
                                name=column.name,
                                target_type=target_type,
                                add_missing=True,
                                fill_value=column_policy.fill_value,
                            )
                        )
                        continue

            if target_type is None:
                continue

            actual_type = DataType.from_type(actual_dtypes[column.name])
            if _is_type_compatible(actual_type, target_type):
                continue

            match column_policy.on_type_mismatch:
                case "error":
                    raise NodeValidationError(
                        f"Column '{column.name}' has dtype {actual_dtypes[column.name]!s} "
                        f"({actual_type.value}), expected {column.dtype!r} ({target_type.value})."
                    )
                case "ignore":
                    continue
                case "cast" | "soft_cast" as cast_mode:
                    rules.append(
                        _ColumnExecutionRule(
                            name=column.name,
                            target_type=target_type,
                            cast_mode=cast_mode,
                        )
                    )

        return drop_columns, tuple(rules)

    def _build_output(self) -> dd.DataFrame:
        policy = self._normalize_policy(self.policy)
        self.policy = policy
        drop_columns, rules = self._build_execution_plan(policy)

        meta = _apply_schema_policy_partition(
            self.df._meta.copy(),
            drop_columns=drop_columns,
            rules=rules,
        )
        return self.df.map_partitions(
            _apply_schema_policy_partition,
            drop_columns=drop_columns,
            rules=rules,
            meta=meta,
        )

    def process(self) -> None:
        self.output = self._build_output()

    def process_metadata(self) -> None:
        self.output = self._build_output()
