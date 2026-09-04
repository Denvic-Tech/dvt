from typing import Tuple, Dict, Any, Type
from typing import TYPE_CHECKING

from .base import BaseNodeMeta
from ..exceptions import NodeRegistrationError

if TYPE_CHECKING:
    from src.node_dsl.base_node import BaseNode, DFOutputBaseNode


class DFOutputNodeMeta(BaseNodeMeta):
    def __new__(cls, name: str, bases: Tuple[type, ...], dct: Dict[str, Any]):

        new_cls: Type["BaseNode"] | Type["DFOutputBaseNode"] = super().__new__(cls, name, bases, dct)

        if new_cls.OUTPUT_NODE:
            raise NodeRegistrationError(f"{name}: DFOutputNode cannot be output node (OUTPUT_NODE = True)")

        from src.node_dsl.field import OutputField

        output_field = new_cls._output_field_instances.get("output", None)
        if name != "DFOutputBaseNode" and (output_field is None or not isinstance(output_field, OutputField)):
            raise NodeRegistrationError(f"{name}: Output DataFrame must be defined as an OutputField in the class definition.")

        return new_cls
