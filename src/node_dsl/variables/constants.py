from src.node_dsl.node_typing import IO
from src.node_dsl.variables.types import VariableType

VARIABLE_SCALAR_IOS: tuple[VariableType, ...] = (
    IO.STRING,
    IO.BOOLEAN,
    IO.INT,
    IO.FLOAT,
    IO.DATETIME,
    IO.TIMEDELTA,
    IO.JSON,
)
LIST_VARIABLE_SCALAR_IOS: tuple[VariableType, ...] = (
    IO.STRING,
    IO.BOOLEAN,
    IO.INT,
    IO.FLOAT,
    IO.DATETIME,
    IO.TIMEDELTA,
)
EXPRESSION_VARIABLE_SCALAR_IOS: tuple[VariableType, ...] = (
    IO.STRING,
    IO.BOOLEAN,
    IO.INT,
    IO.FLOAT,
    IO.DATETIME,
    IO.TIMEDELTA,
    IO.JSON,
)
