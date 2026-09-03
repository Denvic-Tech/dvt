from typing import Tuple, Dict, Any, Type
from typing import TYPE_CHECKING

from .base import BaseNodeMeta

if TYPE_CHECKING:
    from src.node_dsl.base_node import BaseNode, PrimitiveBaseNode


class PrimitiveNodeMeta(BaseNodeMeta):
    def __new__(cls, name: str, bases: Tuple[type, ...], dct: Dict[str, Any]):

        new_cls: Type["BaseNode"] | Type["PrimitiveBaseNode"] = super().__new__(cls, name, bases, dct)

        if name == "PrimitiveBaseNode":
            return type.__new__(cls, name, bases, dct)

        # TODO: МБ добавить проверку output на примитивность

        return new_cls
