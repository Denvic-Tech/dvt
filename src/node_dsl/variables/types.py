from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, Field

from src.node_dsl.node_typing import IO


VariableType: TypeAlias = Literal[
    IO.STRING,
    IO.BOOLEAN,
    IO.INT,
    IO.FLOAT,
    IO.DATETIME,
    IO.TIMEDELTA,
    IO.JSON,
]

VariableValue: TypeAlias = Any

VariableScope: TypeAlias = Literal["user", "system"]
VariableValueState: TypeAlias = Literal["resolved", "unresolved"]


@dataclass(frozen=True)
class UnresolvedValue:
    kind: Literal["UNRESOLVED"] = "UNRESOLVED"
    reason: str | None = None
    declared_type: VariableType | str | None = None
    is_list_type: bool = False


@dataclass
class VariableOutput:
    name: str
    type: VariableType
    value: Any
    var_type: VariableScope = "user"
    is_list_type: bool = False


class VariableDescriptorMetadata(BaseModel):
    name: str = Field(description="Имя переменной")
    type: VariableType = Field(description="Тип переменной")
    var_type: VariableScope = Field(default="user", description="Область переменной")
    is_list_type: bool = Field(default=False, description="Признак переменной-списка")
    value_state: VariableValueState = Field(
        default="resolved",
        description="Состояние значения переменной",
    )


class VariableMapMetadata(BaseModel):
    type: Literal["VARIABLE_MAP"] = "VARIABLE_MAP"
    variables: list[VariableDescriptorMetadata] = Field(
        default_factory=list,
        description="Метаданные переменных выходного порта",
    )
