from abc import ABC

import sqlalchemy as sa

from .base import BaseNode

from src.node_dsl.node_meta import InternalNodeMeta
from src import enums


class PrimitiveBaseNode(BaseNode, ABC, metaclass=InternalNodeMeta):
    """
    Базовый класс для примитивных нод.
    """

    # --- Атрибуты класса для метаданных ---
    TYPE = enums.NodeType.PRIMITIVE
