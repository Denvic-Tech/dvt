from typing import Union, Tuple, Dict, Any, Type
from typing import TYPE_CHECKING

from .base import BaseNodeMeta
from ..exceptions import NodeRegistrationError

if TYPE_CHECKING:
    from src.node_dsl.base_node import (
        BaseNode,
        SqlConnectionOutputBaseNode,
        KafkaConnectionOutputBaseNode
    )

NEW_CLS_TYPE = Union[
    Type["BaseNode"],
    Type["SqlConnectionOutputBaseNode"],
    Type["KafkaConnectionOutputBaseNode"]
]


class ConnectionOutputNodeMeta(BaseNodeMeta):
    def __new__(cls, name: str, bases: Tuple[type, ...], dct: Dict[str, Any]):
        new_cls: NEW_CLS_TYPE = super().__new__(cls, name, bases, dct)

        connection_field = new_cls._output_field_instances.get("connection", None)

        from src.node_dsl.field import OutputField

        if (
                name not in [
                    "SqlConnectionOutputBaseNode",
                    "KafkaConnectionOutputBaseNode",
                    "S3ConnectionOutputBaseNode",
                    "FTPConnectionOutputBaseNode",
                    "SMBConnectionOutputBaseNode",
                ]
                and (connection_field is None or not isinstance(connection_field, OutputField))
        ):
            raise NodeRegistrationError(
                f"{name}: Output connection must be defined as an OutputField in the class definition."
            )

        return new_cls
