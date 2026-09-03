from typing import Any, Literal

from pydantic import BaseModel, Field

from src import enums
from src.node_dsl import node_typing
from src.node_dsl.constants import NodeInputNames, NodeOutputNames

LiteralInputDefinitionKey = Literal[NodeInputNames.VARIABLES, NodeInputNames.SIGNAL]
LiteralOutputDefinitionKey = Literal[
    NodeOutputNames.VARIABLES,
    NodeOutputNames.SIGNAL,
    NodeOutputNames.ERROR_SIGNAL,
]

InputDefinitionKey = str | LiteralInputDefinitionKey
OutputDefinitionKey = str | LiteralOutputDefinitionKey

class InputDefinitionModel(BaseModel):
    """Определение входного поля ноды."""
    attr_name: InputDefinitionKey = Field(description="Имя атрибута в классе Python")
    display_name: str | None = Field(None, description="Отображаемое имя (для UI)", json_schema_extra={"i18n": True})
    type: node_typing.IO | list[node_typing.IO] = Field(description="Строковое представление типа ComfyUI")
    display_type: str | None = Field(None, description="Отображаемый тип (для UI)", json_schema_extra={"i18n": True})
    is_list_type: bool = Field(description="Является ли тип списком")
    is_literal_type: bool = Field(description="Является ли тип выбором (COMBO)")
    options: list[str] | None = Field(None, description="Возможные значения (для выбора)")
    optional: bool = Field(description="Является ли поле опциональным")
    is_hidden: bool = Field(description="Является ли поле скрытым")
    description: str | None = Field(None, description="Описание поля", json_schema_extra={"i18n": True})
    default: Any | None = Field(None, description="Значение по умолчанию")
    multiline: bool | None = Field(None, description="Подсказка UI: многострочный ввод")
    metadata_source_field: str | None = Field(None, description="Названия поля для источника метаданных")
    min_value: int | float | None = Field(None, description="Минимальное значение (для чисел)")
    max_value: int | float | None = Field(None, description="Максимальное значение (для чисел)")
    step: int | float | None = Field(None, description="Шаг (для чисел)")
    round_val: int | float | None = Field(None, description="Округление (для чисел)")
    schema: dict | None = Field(None, description="Дополнительная схема для виджета")
    allow_multiple_connections: bool | None = Field(False, description="Разрешить множественные подключения")
    allow_new: bool | None = Field(False, description="Разрешить новые имена колонок (только для \"IO.COLUMN_NAME\"")
    allow_expressions: bool | None = Field(True, description="Разрешены ли вычисляемые значения")
    expression_policy: str | None = Field(None, description="Имя политики sandbox для выражений")
    force_handle_visible: bool | None = Field(False, description="Всегда показывать handle")
    use_widget: bool | None = Field(None, description="Переопределение использование виджета")
    use_connection: bool | None = Field(None, description="Переопределение использование коннекта")


class OutputDefinitionModel(BaseModel):
    """Определение выходного поля ноды."""
    attr_name: OutputDefinitionKey = Field(description="Имя атрибута в классе Python")
    display_name: str | None = Field(None, description="Отображаемое имя (для UI)", json_schema_extra={"i18n": True})
    type: node_typing.IO | list[node_typing.IO] = Field(description="Строковое представление типа ComfyUI")
    display_type: str | None = Field(None, description="Отображаемый тип (для UI)", json_schema_extra={"i18n": True})
    is_list_type: bool = Field(description="Является ли тип списком")
    description: str | None = Field(None, description="Описание поля", json_schema_extra={"i18n": True})
    tooltip: str | None = Field(None, description="Подсказка для выхода")
    force_handle_visible: bool | None = Field(False, description="Всегда показывать handle")


class SystemVariableDefinitionModel(BaseModel):
    type: node_typing.IO = Field(description="Тип системной переменной")
    required: bool = Field(description="Обязательна ли системная переменная в runtime")
    display_name: str | None = Field(None, description="Отображаемое имя системной переменной")
    description: str | None = Field(None, description="Описание системной переменной")


class BaseVariableDefinitionModel(BaseModel):
    type: node_typing.IO = Field(description="Тип базовой runtime-переменной")
    required: bool = Field(description="Обязательна ли базовая переменная в runtime")
    display_name: str | None = Field(None, description="Отображаемое имя базовой переменной")
    description: str | None = Field(None, description="Описание базовой переменной")


class NodeDefinition(BaseModel):
    """
    Обновленное определение ноды для передачи клиенту.
    Включает маппинги определений входов/выходов.
    """
    # --- Определения входов/выходов ---
    input_definitions: dict[InputDefinitionKey, InputDefinitionModel] = Field(
        description="Mapping определений входных полей по attr_name"
    )
    output_definitions: dict[OutputDefinitionKey, OutputDefinitionModel] = Field(
        description="Mapping определений выходных полей по attr_name"
    )
    system_variable_definitions: dict[str, SystemVariableDefinitionModel] = Field(
        default_factory=dict,
        description="Mapping определений системных переменных по имени переменной",
    )

    # --- Общие метаданные ---
    name: str = Field(description="Имя класса ноды (уникальный идентификатор)")
    emoji: str | None = Field(default=None, description="Эмодзи иконка для ноды")
    display_name: str = Field(description="Отображаемое имя ноды", json_schema_extra={"i18n": True})
    description: str = Field(default='', description="Описание ноды", json_schema_extra={"i18n": True})
    python_module: str = Field(description="Относительный путь к Python модулю ноды")
    category: str = Field(description="Категория ноды для группировки")
    category_color: str = Field(
        description="Hex-цвет категории ноды для UI",
        pattern=r"^#[0-9A-Fa-f]{6}$",
    )
    tags: list[str] = Field(description="Список тегов ноды")
    type: enums.NodeType = Field(description="Типы ноды")
    output_node: bool = Field(description="Является ли нода выходной (конечной точкой)")
    deprecated: bool = Field(default=False, description="Является ли нода устаревшей")
    experimental: bool = Field(default=False, description="Является ли нода экспериментальной")
    visible: bool = Field(default=True, description="Является ли нода видимой")
    documentation_available: bool = Field(
        default=False,
        description="Есть ли для ноды загруженная документация.",
    )
    additional_schema: dict | None = Field(default=None, description="")
    extension_name: str | None = Field(default=None, description="Имя пакета-расширения")
    extension_version: str | None = Field(default=None, description="Версия пакета-расширения")
