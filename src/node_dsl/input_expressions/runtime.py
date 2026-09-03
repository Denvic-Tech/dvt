from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from types import MappingProxyType
from typing import Any

from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment
from jinja2.sandbox import SandboxedEnvironment

from src.node_dsl.constants import DVT_ERROR_TEXT_VARIABLE_NAME

from ._init_registry import ensure_expressions_registry_initialized
from .constants import IMMUTABLE_INPUT_VARIABLES_SYSTEM_ATTRIBUTES_RULE
from .registry import (
    attributes as attributes_registry,
    filters as filters_registry,
    globals as globals_registry,
    tests as tests_registry,
)
from .types import ExpressionPolicy


def _tojson(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class FrozenList(tuple):
    def __new__(cls, items: tuple[Any, ...] | list[Any] | None = None) -> "FrozenList":
        return super().__new__(cls, tuple(items or ()))

    def __add__(self, other: Any) -> "FrozenList":
        if isinstance(other, (list, tuple)):
            return FrozenList(tuple(self) + tuple(other))
        return NotImplemented

    def __radd__(self, other: Any) -> Any:
        if isinstance(other, list):
            return other + list(self)
        if isinstance(other, tuple):
            return other + tuple(self)
        return NotImplemented


def _freeze_value(value: Any) -> Any:
    if isinstance(value, ImmutableVariables):
        return value

    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})

    if isinstance(value, list):
        return FrozenList(_freeze_value(item) for item in value)

    if isinstance(value, tuple):
        return tuple(_freeze_value(item) for item in value)

    if isinstance(value, set):
        return frozenset(_freeze_value(item) for item in value)

    return value


class ImmutableVariables(Mapping[str, Any]):
    def __init__(self, variables: Mapping[str, Any] | None = None):
        self._variables = MappingProxyType(
            {key: _freeze_value(value) for key, value in dict(variables or {}).items()}
        )

    def __getitem__(self, key: str) -> Any:
        return self._variables[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._variables)

    def __len__(self) -> int:
        return len(self._variables)

    def __getattr__(self, item: str) -> Any:
        try:
            return self._variables[item]
        except KeyError as err:
            raise AttributeError(item) from err

    def get(self, key: str, default: Any = None) -> Any:
        return self._variables.get(key, default)

    def as_dict(self) -> dict[str, Any]:
        return dict(self._variables)


class ImmutableInputVariables(ImmutableVariables):
    pass


class ImmutableProjectVariables(ImmutableVariables):
    pass


attributes_registry.add(
    IMMUTABLE_INPUT_VARIABLES_SYSTEM_ATTRIBUTES_RULE,
    owner_type=ImmutableInputVariables,
    attributes={DVT_ERROR_TEXT_VARIABLE_NAME},
)


class _SandboxedNativeEnvironment(SandboxedEnvironment, NativeEnvironment):
    def __init__(self, *args: Any, policy: ExpressionPolicy, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._policy = policy

    def is_safe_attribute(self, obj: Any, attr: str, value: Any) -> bool:
        if attributes_registry.is_allowed(
                self._policy.allowed_attribute_rules,
                obj=obj,
                attr=attr,
        ):
            return True
        if attr.startswith("_"):
            return False
        return super().is_safe_attribute(obj, attr, value)

    def is_safe_callable(self, obj: Any) -> bool:
        return obj in self.globals.values()


def build_environment(policy: ExpressionPolicy) -> _SandboxedNativeEnvironment:
    ensure_expressions_registry_initialized()

    env = _SandboxedNativeEnvironment(
        policy=policy,
        undefined=StrictUndefined,
        autoescape=False,
    )

    allowed_filters = set(policy.allowed_filters)
    env.filters = {
        name: filters_registry.get_callable(name)
        for name in allowed_filters
    }

    allowed_tests = set(policy.allowed_tests)
    env.tests = {
        name: tests_registry.get_callable(name)
        for name in allowed_tests
    }

    allowed_globals = set(policy.allowed_globals)
    env.globals = {
        name: globals_registry.get_callable(name)
        for name in allowed_globals
    }
    return env


def ensure_template_syntax_allowed(expression: str, policy: ExpressionPolicy) -> None:
    if not policy.allow_statements and "{%" in expression:
        raise ValueError("Expression templates do not allow statement blocks.")
    if not policy.allow_comments and "{#" in expression:
        raise ValueError("Expression templates do not allow comments.")
