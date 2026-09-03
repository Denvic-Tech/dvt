from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _NodeInputValueBase(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)


class NodeInputExpressionValue(_NodeInputValueBase):
    dvt_type: Literal["expr"] = Field(default="expr", alias="__dvt_type")
    value: str = Field(description="Текст вычисляемого выражения")
    expression_kind: Literal["single", "template"] = Field(
        description="Тип выражения: одиночное выражение или шаблон",
    )


class NodeInputConstantValue(_NodeInputValueBase):
    dvt_type: Literal["const"] = Field(default="const", alias="__dvt_type")
    value: Any = Field(description="Значение константы")


class NodeInputLinkValue(_NodeInputValueBase):
    dvt_type: Literal["link"] = Field(default="link", alias="__dvt_type")
    node_id: str = Field(description="ID ноды-источника")
    output_name: str = Field(description="Имя выходного поля ноды-источника")


NodeInputValue = Annotated[
    NodeInputExpressionValue | NodeInputConstantValue | NodeInputLinkValue,
    Field(discriminator="dvt_type"),
]

NodeInputValues = dict[str, NodeInputValue]
NodeRuntimeInputValue = NodeInputValue | list[NodeInputLinkValue]
NodeRuntimeInputValues = dict[str, NodeRuntimeInputValue]
