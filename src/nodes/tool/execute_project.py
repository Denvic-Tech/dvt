import asyncio
import inspect
from typing import Any, Literal

import dask.dataframe as dd
import numpy as np
import pandas as pd

from core.types import DataType

from src.infra.task_node_runtime import (
    enqueue_project_task_for_node,
    wait_for_task_terminal_state,
)
from src.logger import logger
from src.node_dsl import IO, NodeValidationError
from src.node_dsl.hooks import on_validation
from src.node_dsl.variables import VariableOutput
from src.node_dsl.variables.type_system import (
    infer_variable_scalar_type_from_data_type,
    infer_variable_scalar_type_from_value,
)
from src.node_dsl import InputField, SignalOutputBaseNode
from src.pipeline.execution_mode import PipelineExecutionMode


def _safe_repr(value: Any, *, max_len: int = 500) -> str:
    try:
        rendered = repr(value)
    except Exception as exc:
        rendered = f"<repr failed: {type(exc).__name__}: {exc}>"
    if len(rendered) <= max_len:
        return rendered
    return f"{rendered[: max_len - 3]}..."


def _describe_awaitable(value: Any, *, operation_name: str, nested_level: int) -> dict[str, Any]:
    running_loop = asyncio.get_running_loop()
    details: dict[str, Any] = {
        "operation_name": operation_name,
        "nested_level": nested_level,
        "awaitable_module": type(value).__module__,
        "awaitable_qualname": type(value).__qualname__,
        "is_awaitable": inspect.isawaitable(value),
        "is_asyncio_future": asyncio.isfuture(value),
        "awaitable_id": id(value),
        "running_loop_id": id(running_loop),
    }

    get_loop = getattr(value, "get_loop", None)
    if callable(get_loop):
        try:
            details["awaitable_loop_id"] = id(get_loop())
        except Exception as exc:
            details["awaitable_loop_error"] = f"{type(exc).__name__}: {exc}"

    done = getattr(value, "done", None)
    if callable(done):
        try:
            details["awaitable_done"] = bool(done())
        except Exception as exc:
            details["awaitable_done_error"] = f"{type(exc).__name__}: {exc}"

    cancelled = getattr(value, "cancelled", None)
    if callable(cancelled):
        try:
            details["awaitable_cancelled"] = bool(cancelled())
        except Exception as exc:
            details["awaitable_cancelled_error"] = f"{type(exc).__name__}: {exc}"

    return details


async def _await_nested_result(awaitable: Any, *, operation_name: str) -> Any:
    result = await awaitable
    nested_level = 0
    while inspect.isawaitable(result):
        nested_level += 1
        awaitable_details = _describe_awaitable(
            result,
            operation_name=operation_name,
            nested_level=nested_level,
        )
        logger.warning(f"ExecuteProject helper returned nested awaitable: \n{awaitable_details}")
        try:
            result = await result
        except Exception:
            logger.exception(
                f"ExecuteProject nested awaitable failed: \n{awaitable_details}",
                awaitable_repr=_safe_repr(result),
            )
            raise
    return result


def _is_missing_dataframe_value(value: Any) -> bool:
    if value is None or value is pd.NaT:
        return True

    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _normalize_dataframe_variable_value(value: Any) -> Any:
    if _is_missing_dataframe_value(value):
        value = None
    elif isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    elif isinstance(value, pd.Timedelta):
        value = value.to_pytimedelta()
    elif isinstance(value, np.generic):
        value = value.item()
    elif isinstance(value, tuple):
        value = list(value)
    elif isinstance(value, set):
        value = sorted(value)
    return value


def _infer_dataframe_variable_type(value: Any, source_dtype: Any) -> IO:
    if value is not None:
        return infer_variable_scalar_type_from_value(value)

    return infer_variable_scalar_type_from_data_type(DataType.from_type(source_dtype)) or IO.JSON


class ExecuteProject(SignalOutputBaseNode):
    TITLE = "Execute Project"
    EMOJI = "🗂️"
    CATEGORY = "Tool"

    target_project_id: str = InputField(description="ID of project to execute")
    target_project_name: str | None = InputField(
        default=None,
        description="Display name of project to execute for UI snapshot rendering",
    )
    variables_df: dd.DataFrame | None = InputField(
        default=None,
        description=("Rows to execute sequentially; column names become child project variables"),
    )
    wait_for_completion: bool = InputField(default=False)
    timeout_sec: int | None = InputField(default=None, min_value=1)
    cancel_on_timeout: bool = InputField(default=False)
    unresolved_variables_policy: Literal["error", "skip"] = InputField(
        default="error",
        description="How to handle unresolved input variables: error | skip",
    )
    system_variables_policy: Literal["error", "skip", "include"] = InputField(
        default="include",
        description="How to handle system input variables: error | skip | include",
    )

    def _validate_dataframe_mode(self) -> None:
        if self.variables_df is not None and not self.wait_for_completion:
            raise NodeValidationError(
                "`variables_df` requires `wait_for_completion=true` for sequential execution."
            )

    @on_validation(name="Validate ExecuteProject DataFrame mode")
    async def validate_dataframe_mode(self) -> None:
        self._validate_dataframe_mode()

    @staticmethod
    def _validate_dataframe_columns(columns: list[Any]) -> list[str]:
        invalid_columns = [
            column_name
            for column_name in columns
            if not isinstance(column_name, str) or not column_name.strip()
        ]
        if invalid_columns:
            raise NodeValidationError(
                f"`variables_df` column names must be non-empty strings: {invalid_columns!r}."
            )

        seen: set[str] = set()
        duplicate_columns: list[str] = []
        for column_name in columns:
            if column_name in seen and column_name not in duplicate_columns:
                duplicate_columns.append(column_name)
            seen.add(column_name)
        if duplicate_columns:
            raise NodeValidationError(
                f"`variables_df` column names must be unique: {duplicate_columns!r}."
            )

        return columns

    async def _build_iteration_variables(self) -> list[dict[str, Any]]:
        base_variables = dict(self.input_variables or {})
        if self.variables_df is None:
            return [base_variables]

        self._validate_dataframe_columns(list(self.variables_df.columns))
        dataframe = await asyncio.to_thread(self.variables_df.compute)
        if not isinstance(dataframe, pd.DataFrame):
            raise TypeError(
                "`variables_df.compute()` must return a pandas DataFrame, "
                f"got {type(dataframe).__name__}."
            )

        column_names = self._validate_dataframe_columns(list(dataframe.columns))
        source_dtypes = list(dataframe.dtypes)
        iteration_variables: list[dict[str, Any]] = []
        for row_values in dataframe.itertuples(index=False, name=None):
            row_variables: dict[str, VariableOutput] = {}
            for column_index, column_name in enumerate(column_names):
                value = _normalize_dataframe_variable_value(row_values[column_index])
                variable_type = _infer_dataframe_variable_type(
                    value,
                    source_dtypes[column_index],
                )
                row_variables[column_name] = VariableOutput(
                    name=column_name,
                    type=variable_type,
                    value=value,
                    var_type="user",
                )
            iteration_variables.append({**base_variables, **row_variables})

        return iteration_variables

    async def _execute_child_iteration(
        self,
        *,
        target_project_id: str,
        variables: dict[str, Any],
        iteration_number: int,
        iteration_count: int,
    ) -> None:
        child_task = await _await_nested_result(
            enqueue_project_task_for_node(
                actor_user_id=self._user_id,
                target_project_id=target_project_id,
                parent_project_id=self._project_id,
                parent_task_id=self._task_id,
                wait_for_completion=bool(self.wait_for_completion),
                force_exec=True,
                variables=variables,
                unresolved_variables_policy=self.unresolved_variables_policy,
                system_variables_policy=self.system_variables_policy,
            ),
            operation_name="enqueue_project_task_for_node",
        )
        child_task_id = getattr(child_task, "task_id", None)
        if not isinstance(child_task_id, str) or not child_task_id.strip():
            raise TypeError(
                "enqueue_project_task_for_node must resolve to an object with non-empty task_id"
            )

        logger.info(
            "ExecuteProject enqueued child task",
            parent_task_id=self._task_id,
            child_task_id=child_task_id,
            target_project_id=target_project_id,
            wait_for_completion=self.wait_for_completion,
            iteration_number=iteration_number,
            iteration_count=iteration_count,
        )

        if self.wait_for_completion:
            await _await_nested_result(
                wait_for_task_terminal_state(
                    child_task_id=child_task_id,
                    timeout_sec=self.timeout_sec,
                    cancel_on_timeout=bool(self.cancel_on_timeout),
                ),
                operation_name="wait_for_task_terminal_state",
            )

    async def process(self) -> None:
        if self.execution_mode == PipelineExecutionMode.METADATA_ONLY:
            self.signal_out = True
            return

        target_project_id = (self.target_project_id or "").strip()
        if not target_project_id:
            raise ValueError("target_project_id is empty")

        self._validate_dataframe_mode()
        iteration_variables = await self._build_iteration_variables()
        iteration_count = len(iteration_variables)

        logger.info(
            "ExecuteProject started",
            parent_task_id=self._task_id,
            parent_project_id=self._project_id,
            target_project_id=target_project_id,
            wait_for_completion=self.wait_for_completion,
            dataframe_mode=self.variables_df is not None,
            iteration_count=iteration_count,
        )

        for iteration_number, variables in enumerate(iteration_variables, start=1):
            await self._execute_child_iteration(
                target_project_id=target_project_id,
                variables=variables,
                iteration_number=iteration_number,
                iteration_count=iteration_count,
            )

        self.signal_out = True
