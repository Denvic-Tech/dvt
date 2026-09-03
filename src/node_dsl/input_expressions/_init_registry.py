import threading
from typing import Protocol, Callable, Dict, Tuple

from .defaults import (
    DEFAULT_ENVIRONMENT_FILTERS,
    DEFAULT_ENVIRONMENT_TESTS,
    DEFAULT_ENVIRONMENT_GLOBALS,
)

from .registry import (
    filters as filters_registry,
    tests as tests_registry,
    globals as globals_registry,
)


class Registry(Protocol):
    def add(self, name: str, expression: str, callable: Callable, description: str | None) -> None: ...


class EnvironmentEntity(Protocol):
    name: str
    expression: str
    description: str | None


_INIT_LOCK = threading.RLock()
_REGISTRY_INITIALIZED = False


def init_registry(
        registry: Registry,
        defaults: Dict[str, Tuple[Callable, EnvironmentEntity]],
):
    for name, (_callable, definition) in defaults.items():
        registry.add(
            name=name,
            expression=definition.expression,
            callable=_callable,
            description=definition.description,
        )


def init_expressions_registry_with_defaults():
    init_registry(filters_registry, DEFAULT_ENVIRONMENT_FILTERS)
    init_registry(tests_registry, DEFAULT_ENVIRONMENT_TESTS)
    init_registry(globals_registry, DEFAULT_ENVIRONMENT_GLOBALS)


def ensure_expressions_registry_initialized() -> None:
    global _REGISTRY_INITIALIZED

    if _REGISTRY_INITIALIZED:
        return

    with _INIT_LOCK:
        if _REGISTRY_INITIALIZED:
            return
        init_expressions_registry_with_defaults()
        _REGISTRY_INITIALIZED = True
