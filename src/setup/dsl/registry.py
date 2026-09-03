from __future__ import annotations

import threading
from typing import Type

from src.setup.dsl.base import BaseSetupStep


STEP_CLASSES: dict[str, Type[BaseSetupStep]] = {}

_REGISTRY_LOCK = threading.RLock()
_INITIALIZED = False


def add(step_cls: Type[BaseSetupStep]) -> None:
    step_cls.validate_definition()

    with _REGISTRY_LOCK:
        if step_cls.CODE in STEP_CLASSES:
            raise ValueError(f"Setup step '{step_cls.CODE}' is already registered.")
        STEP_CLASSES[step_cls.CODE] = step_cls


def get(step_code: str) -> Type[BaseSetupStep]:
    with _REGISTRY_LOCK:
        step_cls = STEP_CLASSES.get(step_code)
        if step_cls is None:
            raise KeyError(f"Setup step '{step_code}' is not registered.")
        return step_cls


def get_all() -> list[Type[BaseSetupStep]]:
    with _REGISTRY_LOCK:
        return sorted(STEP_CLASSES.values(), key=lambda step_cls: step_cls.sort_key())


def clear() -> None:
    global _INITIALIZED
    with _REGISTRY_LOCK:
        STEP_CLASSES.clear()
        _INITIALIZED = False


def is_initialized() -> bool:
    with _REGISTRY_LOCK:
        return _INITIALIZED


def mark_initialized(value: bool) -> None:
    global _INITIALIZED
    with _REGISTRY_LOCK:
        _INITIALIZED = value
