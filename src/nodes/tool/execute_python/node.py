import traceback
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

import pandas as pd
from dask import dataframe as dd
from pydantic import BaseModel

from core.metadata.json_utils import json_safe
from core.types import DataFrameMetadata

from src.logger import logger
from src.node_dsl import IO, DFOutputBaseNode, InputField, OutputField

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


class ExecutePython(DFOutputBaseNode):
    TITLE = "Execute Python"
    EMOJI = "🐍"
    CATEGORY = "Tool"
    TERMINAL_OUTPUT_NAME = "signal_out"
    DESCRIPTION = (
        "Executes arbitrary Python code. "
        "Use df_out and json_out to populate typed outputs."
    )

    df_in: Optional[dd.DataFrame] = InputField(default=None)
    json_in: Optional[IO.JSON] = InputField(default=None)
    code: str = InputField(
        multiline=True,
        allow_expressions=False,
        expression_policy="default",
    )

    signal_out: IO.SIGNAL = OutputField(
        description="Execution signal output",
        force_handle_visible=True,
    )
    output: dd.DataFrame = OutputField(
        description="DataFrame output",
        force_handle_visible=True,
    )
    output_json: IO.JSON = OutputField(
        description="JSON output",
        force_handle_visible=True,
    )

    def _build_exec_locals(self) -> dict[str, Any]:
        output_variables = self.output_variables
        if not isinstance(output_variables, dict):
            output_variables = {}
            self.output_variables = output_variables

        return {
            "node": self,
            "logger": logger,
            "input_variables": self.immutable_input_variables,
            "output_variables": output_variables,
            "project_variables": self.immutable_project_variables,
            "pd": pd,
            "dd": dd,
            "df_in": self.df_in,
            "json_in": self.json_in,
            "df_out": None,
            "json_out": None,
        }

    @staticmethod
    def _normalize_dataframe_output(value: Any) -> dd.DataFrame | None:
        if value is None:
            return None

        if isinstance(value, dd.DataFrame):
            return value

        if isinstance(value, pd.DataFrame):
            return dd.from_pandas(value, npartitions=1)

        raise ValueError(
            "Result variable 'df_out' must be a pandas or dask DataFrame "
            f"(got {type(value)})."
        )

    @classmethod
    def _is_supported_json_output(cls, value: Any) -> bool:
        if value is None:
            return True

        if isinstance(value, BaseModel):
            return cls._is_supported_json_output(value.model_dump())

        if isinstance(value, dict):
            return all(cls._is_supported_json_output(item) for item in value.values())

        if isinstance(value, (list, tuple, set)):
            return all(cls._is_supported_json_output(item) for item in value)

        if np is not None and isinstance(value, np.ndarray):
            return cls._is_supported_json_output(value.tolist())

        try:
            if pd.isna(value):
                return True
        except TypeError:
            pass

        if isinstance(value, (str, int, bool, float, datetime, date, pd.Timestamp, Decimal)):
            return True

        if np is not None and isinstance(value, np.generic):
            return cls._is_supported_json_output(value.item())

        return False

    @classmethod
    def _normalize_json_output(cls, value: Any) -> Any:
        if value is None:
            return None

        if not cls._is_supported_json_output(value):
            raise ValueError(
                "Result variable 'json_out' must contain JSON-compatible data "
                f"(got {type(value)})."
            )

        return json_safe(value)

    def process(self) -> None:
        python_code = (self.code or "").strip()
        if not python_code:
            raise ValueError("Python code is empty.")

        logger.warning("Executing arbitrary Python code. Ensure the code is trusted.")

        exec_globals = {"__builtins__": __builtins__}
        exec_locals = self._build_exec_locals()

        self.output = None
        self.output_json = None
        self.signal_out = False

        try:
            exec(python_code, exec_globals, exec_locals)
        except Exception as error:
            logger.error(f"Error while executing Python code: {error}")
            logger.debug(traceback.format_exc())
            raise ValueError(f"Error in provided Python code: {error}") from error

        self.output = self._normalize_dataframe_output(exec_locals.get("df_out"))
        self.output_json = self._normalize_json_output(exec_locals.get("json_out"))
        self.signal_out = True

    async def process_metadata(self) -> None:
        self.output = self.build_empty_ddf_from_metadata(DataFrameMetadata(columns=[]))
        self.output_json = {}
        self.signal_out = True
