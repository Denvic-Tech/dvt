from typing import Any, Dict
from typing import TYPE_CHECKING

from .base import BaseNodeMixin

from src.node_dsl.types import NodeOutput

if TYPE_CHECKING:
    from src.node_dsl.field import InputField, OutputField


class IOFieldsNodeMixin(BaseNodeMixin):

    def __init__(
            self,
            *args,
            **kwargs
    ):
        super().__init__(*args, **kwargs)

    @classmethod
    def input_fields(cls) -> Dict[str, "InputField"]:
        return cls._input_field_instances

    @classmethod
    def output_fields(cls) -> Dict[str, "OutputField"]:
        return cls._output_field_instances

    def get_inputs(self) -> Dict[str, Any]:
        """собирает значения из входных атрибутов экземпляра"""
        return {
            field.attr_name: getattr(self, field.attr_name)
            for field in self._input_field_instances.values()
        }

    def get_outputs(self) -> Dict[str, NodeOutput]:
        """Собирает значения из выходных атрибутов экземпляра."""
        return {
            field.attr_name: NodeOutput(value=getattr(self, field.attr_name, None))
            for field in self._output_field_instances.values()
        }
