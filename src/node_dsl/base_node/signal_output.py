from abc import ABC

from .base import BaseNode

from src.node_dsl.field import OutputField
from src.node_dsl.node_typing import IO
from src import enums


class SignalOutputBaseNode(BaseNode, ABC):
    """
    Базовый класс для нод, которые имеют SIGNAL в качестве выходного поля.
    """

    TYPE = enums.NodeType.BASE

    signal_out: IO.SIGNAL = OutputField(description="Execution signal output", force_handle_visible=True)
