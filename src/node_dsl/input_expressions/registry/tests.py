import threading
from typing import Callable, Dict

from ..types import EnvironmentTestDefinition

_TESTS_CALLABLE_REGISTRY: Dict[str, Callable] = {}
_TESTS_DEFINITION_REGISTRY: Dict[str, EnvironmentTestDefinition] = {}
_lock = threading.RLock()


def add(
        name: str,
        expression: str,
        callable: Callable,
        description: str | None = None,
) -> None:
    with _lock:
        _TESTS_CALLABLE_REGISTRY[name] = callable
        _TESTS_DEFINITION_REGISTRY[name] = EnvironmentTestDefinition(
            name=name,
            expression=expression,
            description=description,
        )


def get_callable(name: str) -> Callable:
    with _lock:
        if name in _TESTS_CALLABLE_REGISTRY:
            return _TESTS_CALLABLE_REGISTRY[name]
        raise KeyError(f"Callable for environment global {name} not found")


def get_definition(name: str) -> EnvironmentTestDefinition:
    with _lock:
        if name in _TESTS_DEFINITION_REGISTRY:
            return _TESTS_DEFINITION_REGISTRY[name]
        raise KeyError(f"Definition for environment global {name} not found")


def get_all_callables() -> Dict[str, Callable]:
    with _lock:
        return _TESTS_CALLABLE_REGISTRY.copy()


def get_all_definitions() -> Dict[str, EnvironmentTestDefinition]:
    with _lock:
        return _TESTS_DEFINITION_REGISTRY.copy()
