"""Тесты для проверки корректности значений по умолчанию InputField"""
import pytest
from typing import Optional
from src.node_dsl import BaseNode, InputField, OutputField
from src.node_dsl.exceptions import NodeValidationError


class RequiredFieldNode(BaseNode):
    """Тестовая нода с обязательным полем"""
    TITLE = "Required Field Node"

    required_field: str = InputField()
    output: str = OutputField()

    def process(self):
        self.output = self.required_field


class OptionalFieldNode(BaseNode):
    """Тестовая нода с опциональным полем"""
    TITLE = "Optional Field Node"

    optional_explicit: Optional[str] = InputField()
    optional_with_default: Optional[str] = InputField(default=None)
    optional_with_value: str = InputField(default="test_value")
    output: str = OutputField()

    def process(self):
        self.output = "done"


class EqRaisesOnCompare:
    def __eq__(self, other):
        raise NotImplementedError("eq not implemented")


class EqSensitiveRequiredFieldNode(BaseNode):
    TITLE = "Eq Sensitive Required Field Node"

    required_field: object = InputField()
    output: str = OutputField()

    def process(self):
        self.output = "done"


class TestInputFieldDefaults:
    """Тесты для проверки значений по умолчанию InputField"""

    def test_inherited_base_node_field_is_materialized_on_subclass(self):
        """
        BaseNode может содержать "глобальные" input/output поля (например, input_variables/signal).
        Эти поля должны быть:
        - в _input_field_instances / _output_field_instances у наследника,
        - материализованы как обычные атрибуты класса (значение default), а не дескриптор.
        """

        class InheritsBaseNodeFieldNode(BaseNode):
            TITLE = "Inherits BaseNode Field Node"

            output: str = OutputField()

            def process(self):
                self.output = "done"

        # Поле должно быть зарегистрировано как input поле ноды
        assert "input_variables" in InheritsBaseNodeFieldNode._input_field_instances
        assert "signal_in" in InheritsBaseNodeFieldNode._input_field_instances
        assert "output_variables" in InheritsBaseNodeFieldNode._output_field_instances
        assert "signal_out" in InheritsBaseNodeFieldNode._output_field_instances
        assert "signal_error" in InheritsBaseNodeFieldNode._output_field_instances

        # И должно быть "превращено" в значение default на уровне атрибута класса
        assert getattr(InheritsBaseNodeFieldNode, "input_variables") == {}
        assert getattr(InheritsBaseNodeFieldNode, "output_variables") is Ellipsis
        assert getattr(InheritsBaseNodeFieldNode, "signal_in") is None
        assert getattr(InheritsBaseNodeFieldNode, "signal_out") is Ellipsis
        assert getattr(InheritsBaseNodeFieldNode, "signal_error") is Ellipsis

    @pytest.mark.asyncio
    async def test_ellipsis_input_is_treated_as_not_provided_for_optional_field(self):
        node = OptionalFieldNode(
            user_id="test_user",
            project_id="test_project",
            task_id="test_task",
            node_id="test_node",
            optional_explicit=Ellipsis,
        )

        # _set_kwargs должен игнорировать Ellipsis и оставить default None
        assert node.optional_explicit is None
        await node.validate()

    @pytest.mark.asyncio
    async def test_ellipsis_input_still_fails_for_required_field(self):
        node = RequiredFieldNode(
            user_id="test_user",
            project_id="test_project",
            task_id="test_task",
            node_id="test_node",
            required_field=Ellipsis,
        )

        # _set_kwargs игнорирует Ellipsis -> остаётся class default Ellipsis -> validate должна упасть
        assert node.required_field is Ellipsis
        with pytest.raises(NodeValidationError):
            await node.validate()

    @pytest.mark.asyncio
    async def test_none_input_fails_for_required_field(self):
        node = RequiredFieldNode(
            user_id="test_user",
            project_id="test_project",
            task_id="test_task",
            node_id="test_node",
            required_field=None,
        )

        assert node.required_field is None
        with pytest.raises(NodeValidationError):
            await node.validate()

    def test_required_field_has_ellipsis_default(self):
        """Проверяем, что обязательное поле имеет Ellipsis как default"""
        field = RequiredFieldNode._input_field_instances['required_field']
        assert field.optional is False, "Обязательное поле должно иметь optional=False"
        assert field.default is Ellipsis, "Обязательное поле должно иметь default=Ellipsis"

    def test_required_field_class_attribute_is_ellipsis(self):
        """Проверяем, что атрибут класса для обязательного поля = Ellipsis"""
        value = getattr(RequiredFieldNode, 'required_field')
        assert value is Ellipsis, "Атрибут класса для обязательного поля должен быть Ellipsis"

    def test_optional_explicit_field(self):
        """Проверяем поле с явным optional=True"""
        field = OptionalFieldNode._input_field_instances['optional_explicit']
        assert field.optional is True, "Поле с optional=True должно быть опциональным"
        assert field.default is None, "Поле с optional=True и без default должно иметь default=None"

    def test_optional_with_default_none(self):
        """Проверяем поле с default=None"""
        field = OptionalFieldNode._input_field_instances['optional_with_default']
        assert field.optional is True, "Поле с default=None должно быть опциональным"
        assert field.default is None, "Поле с default=None должно иметь default=None"

    def test_optional_with_value(self):
        """Проверяем поле с конкретным default значением"""
        field = OptionalFieldNode._input_field_instances['optional_with_value']
        assert field.optional is False, "Поле с default значением не становится опциональным без Optional"
        assert field.default == "test_value", "Поле должно иметь указанное default значение"

    @pytest.mark.asyncio
    async def test_validation_fails_for_missing_required_field(self):
        """Проверяем, что валидация выдает ошибку для отсутствующего обязательного поля"""
        node = RequiredFieldNode(
            user_id="test_user",
            project_id="test_project",
            task_id="test_task",
            node_id="test_node"
        )

        assert node.required_field is Ellipsis, "Поле должно быть Ellipsis, если не передано"

        with pytest.raises(NodeValidationError) as exc_info:
            await node.validate()

        assert "required_field" in str(exc_info.value)
        assert "required but not provided" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validation_passes_for_provided_required_field(self):
        """Проверяем, что валидация проходит для переданного обязательного поля"""
        node = RequiredFieldNode(
            user_id="test_user",
            project_id="test_project",
            task_id="test_task",
            node_id="test_node",
            required_field="provided_value"
        )

        assert node.required_field == "provided_value"

        # Валидация не должна выдать ошибку
        await node.validate()

    @pytest.mark.asyncio
    async def test_validation_passes_for_optional_fields(self):
        """Проверяем, что валидация проходит для опциональных полей без значений"""
        node = OptionalFieldNode(
            user_id="test_user",
            project_id="test_project",
            task_id="test_task",
            node_id="test_node"
        )

        assert node.optional_explicit is None
        assert node.optional_with_default is None
        assert node.optional_with_value == "test_value"

        # Валидация не должна выдать ошибку
        await node.validate()

    @pytest.mark.asyncio
    async def test_validation_does_not_call_eq_when_checking_required_sentinel_values(self):
        node = EqSensitiveRequiredFieldNode(
            user_id="test_user",
            project_id="test_project",
            task_id="test_task",
            node_id="test_node",
            required_field=EqRaisesOnCompare(),
        )

        await node.validate()
