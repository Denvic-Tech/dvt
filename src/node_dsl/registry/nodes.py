import threading
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from src.db import engine
from src.exceptions import NodeNotFoundError
from src.models.extension import ExtensionRecord

from ._bootstrap import ensure_bootstrapped, registry_transaction, reset_bootstrap_state

if TYPE_CHECKING:
    from src.node_dsl.base_node import BaseNode


NODE_CLASSES: dict[str, type["BaseNode"]] = {}

_REGISTRY_LOCK = threading.RLock()


def add(node_cls: type["BaseNode"]) -> None:
    with registry_transaction(), _REGISTRY_LOCK:
        if node_cls.__name__ in NODE_CLASSES:
            raise ValueError(f"Node class '{node_cls.__name__}' is already registered.")

        NODE_CLASSES[node_cls.__name__] = node_cls


def get(node_name: str) -> type["BaseNode"]:
    with registry_transaction(), _REGISTRY_LOCK:
        node_cls = NODE_CLASSES.get(node_name)

    if not node_cls:
        ensure_bootstrapped(is_ready=lambda: bool(NODE_CLASSES))
        with registry_transaction(), _REGISTRY_LOCK:
            node_cls = NODE_CLASSES.get(node_name)

    if not node_cls:
        raise NodeNotFoundError(f"Node '{node_name}' not found in registry.")
    extension_name = getattr(node_cls, "EXTENSION_NAME", None)
    if extension_name:
        with Session(engine) as session:
            extension = session.exec(
                select(ExtensionRecord).where(ExtensionRecord.name == extension_name)
            ).first()
            if extension is None or not extension.is_installed or not extension.is_enabled:
                raise NodeNotFoundError(f"Extension node '{node_name}' is disabled or not installed.")
    return node_cls


def get_all() -> dict[str, type["BaseNode"]]:
    ensure_bootstrapped(is_ready=lambda: bool(NODE_CLASSES))
    with registry_transaction(), _REGISTRY_LOCK:
        return NODE_CLASSES.copy()


def clear() -> None:
    with registry_transaction(), _REGISTRY_LOCK:
        NODE_CLASSES.clear()
    reset_bootstrap_state()
