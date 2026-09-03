from typing import TYPE_CHECKING, Any, Optional, Union

from src.node_dsl import node_typing
from src.node_dsl.input_expressions import ExpressionPolicyRef, get_expression_policy_name

if TYPE_CHECKING:
    from src.schemas.node_definition import InputDefinitionModel, OutputDefinitionModel


class FieldBase[T]:
    """Базовый класс для полей ввода/вывода ноды (Дескриптор)."""

    def __init__(
            self,
            description: str | None = None,
            force_handle_visible: bool | None = False,  # Показывать handle, даже если он скрыт
    ):
        self.description = description
        self.force_handle_visible = force_handle_visible

        # Атрибуты, устанавливаемые метаклассом или __set_name__
        self.attr_name: str | None = None  # Имя атрибута в классе Python
        self.assigned_type: node_typing.IO | list[node_typing.IO] | None = None
        self.resolved_type: node_typing.IO | list[node_typing.IO] | None = None
        self.is_list_type: bool = False  # Является ли тип списком/выбором

    def __set_name__(self, owner: type, name: str):
        """Вызывается при создании класса для установки имени атрибута."""
        self.attr_name = name

    def validate_attrs(self):
        if self.attr_name is None:
            # Это может произойти, если поле используется не как атрибут класса
            raise AttributeError(
                f"Field attribute name not set for field intended as '{self.attr_name or 'unnamed'}'. "
                f"Ensure it's a class attribute."
            )

        if self.resolved_type is None:
            raise ValueError(f"Field type not set for field '{self.attr_name}'.")


class InputField[T](FieldBase[T]):
    """Представляет входное поле ноды."""

    def __init__(
            self,
            description: str | None = None,
            default: Any = ...,  # Используем ... для обозначения отсутствия значения по умолчанию (обязательное поле)
            is_hidden: bool = False,  # Является ли поле скрытым
            multiline: bool = False,  # Подсказка для UI (для строковых полей)
            metadata_source_field: str | None = None,  # Имя поля для источника метаданных

            # --- Дополнительные параметры для UI/валидации (если нужны) ---
            min_value: int | float | None = None,
            max_value: int | float | None = None,
            step: int | float | None = None,
            round_val: int | float | None = None,  # Округление для float/int
            force_handle_visible: bool | None = False,

            use_widget: bool | None = None,
            use_connection: bool | None = None,

            allow_multiple_connections: bool = False, # Принимать несколько подключений
            allow_variables: bool = True,
            allow_expressions: bool = True,

            allow_new: bool | None = False, # Для InputField[IO.COLUMN_NAME]

            expression_policy: ExpressionPolicyRef = "default",
            sql_template: bool = False,
    ):
        super().__init__(
            description=description,
            force_handle_visible=force_handle_visible
        )

        self.optional = Ellipsis
        self.default = default

        self.is_hidden = is_hidden
        self.multiline = multiline
        self.metadata_source_field = metadata_source_field

        self.min_value = min_value
        self.max_value = max_value
        self.step = step
        self.round_val = round_val
        self.allow_multiple_connections = allow_multiple_connections
        self.allow_variables = allow_variables
        self.allow_new = allow_new
        self.allow_expressions = allow_expressions
        self.expression_policy = expression_policy
        # Runtime-only marker. It deliberately is not exposed in NodeDefinition/OpenAPI.
        self.sql_template = sql_template

        self.use_widget = use_widget
        self.use_connection = use_connection

        # Атрибуты, устанавливаемые метаклассом или __set_name__
        self.is_literal_type = False
        self.options: list[str] | None = None
        self.schema: dict | None = None

    def get_definition(self) -> "InputDefinitionModel":
        from src.schemas.node_definition import InputDefinitionModel
        self.validate_attrs()

        return InputDefinitionModel(
            attr_name=self.attr_name,
            display_name=self.attr_name,
            type=self.resolved_type,
            display_type=self.resolved_type,
            is_list_type=self.is_list_type,
            is_literal_type=self.is_literal_type,
            options=self.options,
            optional=self.optional,
            is_hidden=self.is_hidden,
            description=self.description,
            default=self.default if self.default is not ... else None,
            multiline=self.multiline,
            metadata_source_field=self.metadata_source_field,
            min_value=self.min_value,
            max_value=self.max_value,
            step=self.step,
            round_val=self.round_val,
            schema=self.schema,
            allow_multiple_connections=self.allow_multiple_connections,
            allow_new=self.allow_new,
            allow_expressions=self.allow_expressions,
            expression_policy=get_expression_policy_name(self.expression_policy),
            force_handle_visible=self.force_handle_visible,
            use_widget=self.use_widget,
            use_connection=self.use_connection,
        )


class OutputField[T](FieldBase[T]):
    """Представляет выходное поле ноды."""

    def __init__(
            self,
            description: str | None = None,
            force_handle_visible: bool | None = False,

            # --- Дополнительные параметры ---
            is_list: bool = False,  # Явно указать, что выход является списком (для случаев, когда тип не list[T])
            tooltip: str | None = None,  # Подсказка для выхода
    ):
        super().__init__(
            description=description,
            force_handle_visible=force_handle_visible,
        )
        self.is_list_override = is_list  # Флаг для переопределения is_list_type
        self.tooltip = tooltip

    def get_definition(self) -> "OutputDefinitionModel":
        self.validate_attrs()
        from src.schemas.node_definition import OutputDefinitionModel

        return OutputDefinitionModel(
            attr_name=self.attr_name,
            display_name=self.attr_name,
            type=self.resolved_type,
            display_type=str(self.resolved_type),
            is_list_type=self.is_list_override or self.is_list_type,
            description=self.description,
            tooltip=self.tooltip,
            force_handle_visible=self.force_handle_visible,
        )
