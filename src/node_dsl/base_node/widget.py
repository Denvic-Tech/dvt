from abc import ABC

from .base import BaseNode

from src.node_dsl.node_meta import WidgetNodeMeta
from src import enums


class WidgetBaseNode(BaseNode, ABC, metaclass=WidgetNodeMeta):
    """
    Базовый класс для примитивных нод.
    """

    # --- Атрибуты класса для метаданных ---
    TYPE = enums.NodeType.WIDGET

    # Ноды виджеты не будут выполняться
    def process(self) -> None:
        pass
