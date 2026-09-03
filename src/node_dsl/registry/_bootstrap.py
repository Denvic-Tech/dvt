from collections.abc import Callable
from contextlib import contextmanager

from src.extensions._runtime_lock import RUNTIME_LOCK

_REGISTRY_INIT_LOCK = RUNTIME_LOCK
_REGISTRY_INITIALIZING = False
_REGISTRY_BOOTSTRAPPED = False


@contextmanager
def registry_transaction():
    with _REGISTRY_INIT_LOCK:
        yield


def ensure_bootstrapped(*, is_ready: Callable[[], bool], force: bool = False) -> None:
    global _REGISTRY_INITIALIZING, _REGISTRY_BOOTSTRAPPED

    if is_ready() and _REGISTRY_BOOTSTRAPPED and not force:
        return

    with _REGISTRY_INIT_LOCK:
        if is_ready() and _REGISTRY_BOOTSTRAPPED and not force:
            return

        if _REGISTRY_INITIALIZING:
            return

        _REGISTRY_INITIALIZING = True
        try:
            from src.node_dsl._init_nodes import init_nodes

            init_nodes()
            _REGISTRY_BOOTSTRAPPED = True
        finally:
            _REGISTRY_INITIALIZING = False


def mark_bootstrapped() -> None:
    global _REGISTRY_BOOTSTRAPPED
    _REGISTRY_BOOTSTRAPPED = True


def reset_bootstrap_state() -> None:
    global _REGISTRY_BOOTSTRAPPED
    _REGISTRY_BOOTSTRAPPED = False
