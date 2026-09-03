from abc import ABC
from typing import Any

import sqlalchemy as sa
from kafka import KafkaProducer

from .base import BaseNode

from src.node_dsl.node_meta import ConnectionOutputNodeMeta

from src import enums


class SqlConnectionOutputBaseNode(BaseNode, ABC, metaclass=ConnectionOutputNodeMeta):
    """
    Базовый класс для нод, которые имеют Engine в качестве выходного поля.
    Предоставляет удобный интерфейс для работы с Engine.
    """

    # --- Атрибуты класса для метаданных ---
    TYPE = enums.NodeType.CONNECTION_OUTPUT

    # --- Outputs ---
    connection: sa.Engine = None


class KafkaConnectionOutputBaseNode(BaseNode, ABC, metaclass=ConnectionOutputNodeMeta):
    """
    Базовый класс для нод, которые имеют Engine в качестве выходного поля.
    Предоставляет удобный интерфейс для работы с Engine.
    """

    # --- Атрибуты класса для метаданных ---
    TYPE = enums.NodeType.CONNECTION_OUTPUT

    # --- Outputs ---
    connection: KafkaProducer = None


class S3ConnectionOutputBaseNode(BaseNode, ABC, metaclass=ConnectionOutputNodeMeta):
    """
    Базовый класс для нод, которые имеют S3 клиент в качестве выходного поля.
    Предоставляет удобный интерфейс для работы с S3.
    """

    # --- Атрибуты класса для метаданных ---
    TYPE = enums.NodeType.CONNECTION_OUTPUT

    # --- Outputs ---
    connection: Any = None


class FTPConnectionOutputBaseNode(BaseNode, ABC, metaclass=ConnectionOutputNodeMeta):
    """
    Базовый класс для нод, которые имеют FTP клиент в качестве выходного поля.
    Предоставляет удобный интерфейс для работы с FTP.
    """

    # --- Атрибуты класса для метаданных ---
    TYPE = enums.NodeType.CONNECTION_OUTPUT

    # --- Outputs ---
    connection: Any = None


class SMBConnectionOutputBaseNode(BaseNode, ABC, metaclass=ConnectionOutputNodeMeta):
    """
    Базовый класс для нод, которые имеют SMB клиент в качестве выходного поля.
    Предоставляет удобный интерфейс для работы с SMB.
    """

    TYPE = enums.NodeType.CONNECTION_OUTPUT

    # --- Outputs ---
    connection: Any = None
