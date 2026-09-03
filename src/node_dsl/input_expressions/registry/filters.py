import threading
from typing import Callable, Dict

from ..types import EnvironmentFilterDefinition

_FILTERS_CALLABLE_REGISTRY: Dict[str, Callable] = {}
_FILTERS_DEFINITION_REGISTRY: Dict[str, EnvironmentFilterDefinition] = {}
_lock = threading.RLock()


def add(
        name: str,
        expression: str,
        callable: Callable,
        description: str | None = None,
) -> None:
    with _lock:
        _FILTERS_CALLABLE_REGISTRY[name] = callable
        _FILTERS_DEFINITION_REGISTRY[name] = EnvironmentFilterDefinition(
            name=name,
            expression=expression,
            description=description,
        )


def get_callable(name: str) -> Callable:
    with _lock:
        if name in _FILTERS_CALLABLE_REGISTRY:
            return _FILTERS_CALLABLE_REGISTRY[name]
        raise KeyError(f"Callable for environment filter {name} not found")


def get_definition(name: str) -> EnvironmentFilterDefinition:
    with _lock:
        if name in _FILTERS_DEFINITION_REGISTRY:
            return _FILTERS_DEFINITION_REGISTRY[name]
        raise KeyError(f"Definition for environment filter {name} not found")


def get_all_callables() -> Dict[str, Callable]:
    with _lock:
        return _FILTERS_CALLABLE_REGISTRY.copy()


def get_all_definitions() -> Dict[str, EnvironmentFilterDefinition]:
    with _lock:
        return _FILTERS_DEFINITION_REGISTRY.copy()
