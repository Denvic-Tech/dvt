import threading
from typing import Callable, Dict

from ..types import EnvironmentGlobalDefinition

_GLOBALS_CALLABLE_REGISTRY: Dict[str, Callable] = {}
_GLOBALS_DEFINITION_REGISTRY: Dict[str, EnvironmentGlobalDefinition] = {}
_lock = threading.RLock()


def add(
        name: str,
        expression: str,
        callable: Callable,
        description: str | None = None,
) -> None:
    with _lock:
        _GLOBALS_CALLABLE_REGISTRY[name] = callable
        _GLOBALS_DEFINITION_REGISTRY[name] = EnvironmentGlobalDefinition(
            name=name,
            expression=expression,
            description=description,
        )


def get_callable(name: str) -> Callable:
    with _lock:
        if name in _GLOBALS_CALLABLE_REGISTRY:
            return _GLOBALS_CALLABLE_REGISTRY[name]
        raise KeyError(f"Callable for environment global {name} not found")


def get_definition(name: str) -> EnvironmentGlobalDefinition:
    with _lock:
        if name in _GLOBALS_DEFINITION_REGISTRY:
            return _GLOBALS_DEFINITION_REGISTRY[name]
        raise KeyError(f"Definition for environment global {name} not found")


def get_all_callables() -> Dict[str, Callable]:
    with _lock:
        return _GLOBALS_CALLABLE_REGISTRY.copy()


def get_all_definitions() -> Dict[str, EnvironmentGlobalDefinition]:
    with _lock:
        return _GLOBALS_DEFINITION_REGISTRY.copy()
