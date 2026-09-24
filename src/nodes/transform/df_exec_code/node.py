import traceback

import pandas as pd
from dask import dataframe as dd

from src.logger import logger
from src.node_dsl import DFOutputBaseNode, InputField, OutputField


class DataFrameExecCode(DFOutputBaseNode):
    TITLE = "Execute Python Code on DataFrame"
    ICON_KEY = "dataframe-exec-code"
    EMOJI = "💻"
    CATEGORY = "Transform"
    # ВНИМАНИЕ: Выполнение произвольного кода может быть небезопасно!
    # Рассмотрите использование более безопасных альтернатив, если возможно.

    df: dd.DataFrame = InputField(
        agent_description=(
            "Connect a Dask DataFrame; it is exposed to code as df_in. Prefer specialized "
            "transforms and justify the custom-code node in its comment."
        ),
    )
    code: str = InputField(
        agent_description=(
            "Assign a Dask DataFrame to df_out; assigning a pandas DataFrame or omitting df_out "
            "fails. Available names include df_in, pd, dd, input_variables and project_variables. "
            "Keep operations lazy where feasible and document why specialized nodes cannot express "
            "the task."
        ),
        multiline=True, default="df_out = df_in",
    )  # Python код
    # Код должен присвоить результат переменной df_out

    output: dd.DataFrame = OutputField()  # Выходной DataFrame

    def process(self):
        logger.warning("Executing arbitrary Python code on DataFrame. Ensure the code is trusted.")
        output_var_name = "df_out"  # Ожидаемое имя выходной переменной

        exec_env = {
            "__builtins__": __builtins__,
            "node": self,
            "logger": logger,
            "input_variables": self.immutable_input_variables,
            "output_variables": self.output_variables or {},
            "project_variables": self.immutable_project_variables,
            "pd": pd,
            "dd": dd,
            "df_in": self.df,
        }

        try:
            # Исполняем код в локальном окружении
            exec(self.code, exec_env, exec_env)  # Передаем только pandas в globals
        except Exception as e:
            logger.error(f"Error executing custom code: {e}")
            logger.debug(traceback.format_exc())
            raise ValueError(f"Error in provided Python code: {e}")

        # Проверяем, была ли создана выходная переменная
        if output_var_name not in exec_env:
            raise ValueError(
                f"Output variable '{output_var_name}' not found after executing code. Make sure your code assigns the result to '{output_var_name}'.")

        result = exec_env[output_var_name]
        if not isinstance(result, dd.DataFrame):
            raise ValueError(f"Result variable '{output_var_name}' is not a dask DataFrame (type: {type(result)}).")

        self.output = result
        logger.info(f"Custom code execution finished. Output DataFrame shape: {self.output.shape}")
