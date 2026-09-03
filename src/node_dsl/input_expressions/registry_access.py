from __future__ import annotations

from ._init_registry import ensure_expressions_registry_initialized
from .defaults import DEFAULT_EXPRESSION_POLICY
from .registry import (
    filters as filters_registry,
    globals as globals_registry,
    tests as tests_registry,
)
from .types import (
    EnvironmentFilterDefinition,
    EnvironmentGlobalDefinition,
    EnvironmentTestDefinition,
    ExpressionPolicy,
)


def get_registered_expression_filters() -> list[EnvironmentFilterDefinition]:
    ensure_expressions_registry_initialized()
    return sorted(
        filters_registry.get_all_definitions().values(),
        key=lambda definition: definition.name,
    )


def get_registered_expression_tests() -> list[EnvironmentTestDefinition]:
    ensure_expressions_registry_initialized()
    return sorted(
        tests_registry.get_all_definitions().values(),
        key=lambda definition: definition.name,
    )


def get_registered_expression_globals() -> list[EnvironmentGlobalDefinition]:
    ensure_expressions_registry_initialized()
    return sorted(
        globals_registry.get_all_definitions().values(),
        key=lambda definition: definition.name,
    )


def get_default_expression_policy() -> ExpressionPolicy:
    return DEFAULT_EXPRESSION_POLICY
