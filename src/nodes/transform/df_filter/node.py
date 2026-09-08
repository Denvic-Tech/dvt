import operator
from functools import reduce
from typing import Annotated, Any, Dict, Literal

import dask.dataframe as dd
import numpy as np
import pandas as pd
from pandas.api import types as pdt
from pydantic import BaseModel, Field, TypeAdapter, ValidationError, model_validator

from core.types.data_type import DataType
from core.utils import get_useful_indexes

from src.logger import logger
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.core.input_values import (
    NodeInputExpressionValue,
    parse_node_input_value,
    resolve_node_input_value,
)
from src.types import EMPTY_STRING_VALUE, NULL_VALUE
from src.utils import dtype_utils

_NULL_CHECK_OPERATORS = {"isnull", "notnull"}
_BINARY_OPERATORS = {"==", "!=", ">", "<", ">=", "<="}
_LIST_OPERATORS = {"isin", "notin"}
_TEXT_OPERATORS = {"contains", "startswith", "endswith"}


class FilterOperand(BaseModel):
    type: Literal["column", "literal", "expression"]
    column: str | None = None
    value: Any | None = None

    @model_validator(mode="after")
    def _validate_operand_shape(self) -> "FilterOperand":
        if self.type == "column":
            if not isinstance(self.column, str) or not self.column.strip():
                raise ValueError("Column operand requires non-empty 'column'.")
            return self

        if self.column not in (None, ""):
            operand_label = "Expression" if self.type == "expression" else "Literal"
            raise ValueError(f"{operand_label} operand must not define 'column'.")

        if self.type == "expression":
            parsed_value = parse_node_input_value(self.value)
            if not isinstance(parsed_value, NodeInputExpressionValue):
                raise ValueError("Expression operand requires canonical '__dvt_type=expr' value.")
            if parsed_value.expression_kind != "single":
                raise ValueError("Expression operand supports only 'single' expression_kind.")
        return self


class FilterCondition(BaseModel):
    kind: Literal["condition"] = "condition"
    left: FilterOperand
    operator: Literal[
        "==", "!=", ">", "<", ">=", "<=",
        "isin", "notin", "contains", "startswith", "endswith",
        "isnull", "notnull",
    ]
    right: FilterOperand | None = None

    @model_validator(mode="after")
    def _validate_condition(self) -> "FilterCondition":
        if self.operator in _NULL_CHECK_OPERATORS:
            if self.right is not None:
                raise ValueError(f"Operator '{self.operator}' must not define 'right'.")
            return self

        if self.right is None:
            raise ValueError(f"Operator '{self.operator}' requires 'right'.")

        if self.operator in _TEXT_OPERATORS and self.right.type == "column":
            raise ValueError(
                f"Operator '{self.operator}' supports only literal or expression right operand."
            )

        if self.operator in _LIST_OPERATORS and self.right.type == "column":
            raise ValueError(
                f"Operator '{self.operator}' supports only literal or expression list right operand."
            )

        return self


class FilterAND(BaseModel):
    kind: Literal["and"] = "and"
    conditions: list["FilterNode"]

    @model_validator(mode="after")
    def _validate_conditions(self) -> "FilterAND":
        if not self.conditions:
            raise ValueError("AND group must contain at least one condition.")
        return self


class FilterOR(BaseModel):
    kind: Literal["or"] = "or"
    conditions: list["FilterNode"]

    @model_validator(mode="after")
    def _validate_conditions(self) -> "FilterOR":
        if not self.conditions:
            raise ValueError("OR group must contain at least one condition.")
        return self


FilterNode = Annotated[FilterCondition | FilterAND | FilterOR, Field(discriminator="kind")]
FilterAND.model_rebuild()
FilterOR.model_rebuild()
_FILTER_NODE_ADAPTER = TypeAdapter(FilterNode)


def _build_rules_spec() -> Dict[str, Any]:
    data_types = [dtype.value for dtype in DataType]
    operators = sorted(_NULL_CHECK_OPERATORS | _BINARY_OPERATORS | _LIST_OPERATORS | _TEXT_OPERATORS)

    return {
        "version": 3,
        "null_literal_token": NULL_VALUE,
        "empty_string_literal_token": EMPTY_STRING_VALUE,
        "operand_types": ["column", "literal", "expression"],
        "expression_operand": {
            "enabled": True,
            "expression_kind": "single",
            "value_payload_type": "NodeInputExpressionValue",
        },
        "node_kinds": ["condition", "and", "or"],
        "operators": operators,
        "operators_without_right": sorted(_NULL_CHECK_OPERATORS),
        "operators_with_list_right": sorted(_LIST_OPERATORS),
        "operators_with_literal_right_only": sorted(_LIST_OPERATORS | _TEXT_OPERATORS),
        "known_data_types": data_types,
    }


def _normalize_mask(mask: dd.Series) -> dd.Series:
    if not isinstance(mask, dd.Series):
        raise TypeError(f"Expected dask.Series mask, got {type(mask)}")

    mask = mask.fillna(False).astype("bool")
    try:
        mask = mask.rename(None)
    except Exception:
        pass
    return mask


def _constant_mask(df: dd.DataFrame, value: bool) -> dd.Series:
    return dd.map_partitions(
        lambda pdf: pd.Series(bool(value), index=pdf.index, dtype="bool"),
        df,
        meta=pd.Series(dtype="bool"),
    )


def _to_mask(df: dd.DataFrame, value: dd.Series | bool) -> dd.Series:
    if isinstance(value, dd.Series):
        return _normalize_mask(value)

    if isinstance(value, (bool, np.bool_)):
        return _normalize_mask(_constant_mask(df, bool(value)))

    raise TypeError(f"Expected dask.Series or bool, got {type(value)}")


def _apply_mask_df(df: dd.DataFrame, mask: dd.Series) -> dd.DataFrame:
    normalized_mask = _normalize_mask(mask)
    return dd.map_partitions(
        lambda pdf, mask_part: pdf[mask_part],
        df,
        normalized_mask,
        meta=df._meta,
    )


def _invert_mask(mask: dd.Series) -> dd.Series:
    return _normalize_mask(~_normalize_mask(mask))


def _coerce_bool_like(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, int) and value in (0, 1):
        return bool(value)

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "t", "1", "yes", "y"):
            return True
        if normalized in ("false", "f", "0", "no", "n"):
            return False

    raise ValueError(f"Invalid boolean literal: {value!r}")


def _normalize_literal(value: Any) -> Any:
    if value is None or value == NULL_VALUE:
        return None
    if value == EMPTY_STRING_VALUE:
        return ""
    return value


def _resolve_expression_operand(operand: FilterOperand, runtime_variables: Dict[str, Any]) -> Any:
    try:
        return resolve_node_input_value(
            operand.value,
            variables=runtime_variables,
            allow_expressions=True,
            expression_policy="default",
            allow_unresolved=False,
        )
    except ValueError as err:
        raise ValueError(f"Could not resolve expression operand: {err}") from err


def _resolve_operand(
    operand: FilterOperand,
    df: dd.DataFrame,
    useful_indexes: set[str],
    columns_and_indexes: set[str],
    runtime_variables: Dict[str, Any],
) -> tuple[dd.Series | Any, bool]:
    if operand.type == "column":
        column_name = str(operand.column)
        if column_name not in columns_and_indexes:
            raise KeyError(f"Column '{column_name}' not found in DataFrame")

        if column_name in useful_indexes:
            return df.index.to_series(), True
        return df[column_name], True

    if operand.type == "expression":
        return _resolve_expression_operand(operand, runtime_variables), False

    return _normalize_literal(operand.value), False


def _coerce_literal_for_series(value: Any, series: dd.Series) -> Any:
    if value is None:
        return None

    if pdt.is_bool_dtype(series.dtype):
        return _coerce_bool_like(value)

    return dtype_utils.convert_scalar_to_dtype(value, series.dtype)


def _coerce_literal_list_for_series(values: Any, series: dd.Series) -> list[Any]:
    normalized_values = [_normalize_literal(item) for item in dtype_utils.parse_csv_or_list(values)]

    if pdt.is_bool_dtype(series.dtype):
        return [_coerce_bool_like(item) if item is not None else None for item in normalized_values]

    return dtype_utils.convert_list_to_dtype(normalized_values, series.dtype)


def _evaluate_condition(
    condition: FilterCondition,
    df: dd.DataFrame,
    useful_indexes: set[str],
    columns_and_indexes: set[str],
    runtime_variables: Dict[str, Any],
) -> dd.Series:
    left, left_is_series = _resolve_operand(
        condition.left,
        df,
        useful_indexes,
        columns_and_indexes,
        runtime_variables,
    )
    operator_name = condition.operator

    if operator_name in _NULL_CHECK_OPERATORS:
        if left_is_series:
            base_mask = left.isna()  # type: ignore[union-attr]
            return _normalize_mask(~base_mask if operator_name == "notnull" else base_mask)

        scalar_is_null = pd.isna(left)
        if operator_name == "notnull":
            scalar_is_null = not scalar_is_null
        return _to_mask(df, bool(scalar_is_null))

    if condition.right is None:
        raise ValueError(f"Operator '{operator_name}' requires 'right'.")

    right, right_is_series = _resolve_operand(
        condition.right,
        df,
        useful_indexes,
        columns_and_indexes,
        runtime_variables,
    )

    if operator_name in _TEXT_OPERATORS:
        if not left_is_series:
            raise ValueError(f"Operator '{operator_name}' requires column operand on the left.")
        if right_is_series:
            raise ValueError(f"Operator '{operator_name}' does not support column operand on the right.")
        if right is None:
            raise ValueError(f"Operator '{operator_name}' requires non-null literal value.")

        left_str = left.astype("string")  # type: ignore[union-attr]
        if operator_name == "contains":
            return _normalize_mask(left_str.str.contains(str(right), case=False, na=False, regex=False))

        lowered = left_str.str.lower()
        pattern = str(right).lower()
        if operator_name == "startswith":
            return _normalize_mask(lowered.str.startswith(pattern).fillna(False))

        return _normalize_mask(lowered.str.endswith(pattern).fillna(False))

    if operator_name in _LIST_OPERATORS:
        if right_is_series:
            raise ValueError(f"Operator '{operator_name}' does not support column operand on the right.")

        if left_is_series:
            values = _coerce_literal_list_for_series(right, left)  # type: ignore[arg-type]
            mask = left.isin(values)  # type: ignore[union-attr]
        else:
            values = [_normalize_literal(item) for item in dtype_utils.parse_csv_or_list(right)]
            mask = left in values

        if operator_name == "notin":
            mask = ~mask if isinstance(mask, dd.Series) else (not bool(mask))

        return _to_mask(df, mask)

    if operator_name in _BINARY_OPERATORS:
        if operator_name in {">", "<", ">=", "<="} and (left is None or right is None):
            raise ValueError("Relational operators do not support NULL literals.")

        if left_is_series and not right_is_series:
            if right is None and operator_name in {"==", "!="}:
                mask = left.isna()  # type: ignore[union-attr]
                if operator_name == "!=":
                    mask = ~mask
                return _normalize_mask(mask)
            right = _coerce_literal_for_series(right, left)  # type: ignore[arg-type]

        elif not left_is_series and right_is_series:
            if left is None and operator_name in {"==", "!="}:
                mask = right.isna()  # type: ignore[union-attr]
                if operator_name == "!=":
                    mask = ~mask
                return _normalize_mask(mask)
            left = _coerce_literal_for_series(left, right)  # type: ignore[arg-type]

        if operator_name == "==":
            return _to_mask(df, left == right)
        if operator_name == "!=":
            return _to_mask(df, left != right)
        if operator_name == ">":
            return _to_mask(df, left > right)
        if operator_name == "<":
            return _to_mask(df, left < right)
        if operator_name == ">=":
            return _to_mask(df, left >= right)

        return _to_mask(df, left <= right)

    raise ValueError(f"Unsupported operator: {operator_name}")


def _evaluate_filter_tree(
    node: FilterNode,
    df: dd.DataFrame,
    useful_indexes: set[str],
    columns_and_indexes: set[str],
    runtime_variables: Dict[str, Any],
) -> dd.Series:
    if isinstance(node, FilterCondition):
        return _evaluate_condition(
            node,
            df,
            useful_indexes,
            columns_and_indexes,
            runtime_variables,
        )

    if isinstance(node, FilterAND):
        masks = [
            _evaluate_filter_tree(child, df, useful_indexes, columns_and_indexes, runtime_variables)
            for child in node.conditions
        ]
        return _normalize_mask(reduce(operator.and_, masks))

    masks = [
        _evaluate_filter_tree(child, df, useful_indexes, columns_and_indexes, runtime_variables)
        for child in node.conditions
    ]
    return _normalize_mask(reduce(operator.or_, masks))


def _validate_condition_columns(node: FilterNode, columns_and_indexes: set[str]) -> None:
    if isinstance(node, FilterCondition):
        operands = [node.left]
        if node.right is not None:
            operands.append(node.right)

        for operand in operands:
            if operand.type != "column":
                continue
            column_name = str(operand.column)
            if column_name not in columns_and_indexes:
                raise KeyError(f"Column '{column_name}' not found in DataFrame")
        return

    for child in node.conditions:
        _validate_condition_columns(child, columns_and_indexes)


class DataFrameFilter(DFOutputBaseNode):
    TITLE = "Filter DataFrame"
    EMOJI = "🔎"
    CATEGORY = "Transform"

    ADDITIONAL_SCHEMA = {
        "filter_rules_spec": _build_rules_spec(),
    }

    df: dd.DataFrame = InputField()
    conditions: FilterCondition | FilterAND | FilterOR = InputField()

    output: dd.DataFrame = OutputField()
    inverted_output: dd.DataFrame = OutputField()

    def _runtime_variables(self) -> Dict[str, Any]:
        runtime_variables: Dict[str, Any] = {}
        project_variables = self.project_variables
        if project_variables is not None:
            runtime_variables.update(project_variables.raw_values)
        if isinstance(self.input_variables, dict):
            runtime_variables.update(self.input_variables)
        return runtime_variables

    def _parse_conditions(self) -> FilterNode:
        return _FILTER_NODE_ADAPTER.validate_python(self.conditions)

    def process(self) -> None:
        useful_indexes = set(get_useful_indexes(self.df))
        columns_and_indexes = set(self.df.columns).union(useful_indexes)

        try:
            parsed_conditions = self._parse_conditions()
            combined_mask = _evaluate_filter_tree(
                parsed_conditions,
                self.df,
                useful_indexes,
                columns_and_indexes,
                self._runtime_variables(),
            )
        except (ValidationError, Exception) as error:
            logger.error(f"Error while evaluating DataFrameFilter conditions: {error}")
            raise

        self.output = _apply_mask_df(self.df, combined_mask)
        self.inverted_output = _apply_mask_df(self.df, _invert_mask(combined_mask))

    def process_metadata(self) -> None:
        useful_indexes = set(get_useful_indexes(self.df))
        columns_and_indexes = set(self.df.columns).union(useful_indexes)

        try:
            parsed_conditions = self._parse_conditions()
            _validate_condition_columns(parsed_conditions, columns_and_indexes)
        except (ValidationError, Exception) as error:
            logger.error(f"Error while validating DataFrameFilter conditions: {error}")
            raise

        self.output = self.df
        self.inverted_output = self.df
