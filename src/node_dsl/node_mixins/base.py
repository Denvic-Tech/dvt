from typing import ClassVar

from src.node_dsl.field import InputField, OutputField
from src.node_dsl.node_meta.base import collect_mixin_fields


class NodeFieldsMixin:
    __node_field_mixin__ = True
    _mixin_input_field_instances: ClassVar[dict[str, InputField]] = {}
    _mixin_output_field_instances: ClassVar[dict[str, OutputField]] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        input_fields, output_fields = collect_mixin_fields(cls)
        cls._mixin_input_field_instances = input_fields
        cls._mixin_output_field_instances = output_fields
