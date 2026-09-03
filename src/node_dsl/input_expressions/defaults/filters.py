from typing import Dict, Tuple, Callable

from jinja2.filters import FILTERS as JINJA2_FILTERS

from src.node_dsl.input_expressions.types import EnvironmentFilterDefinition

DEFAULT_ENVIRONMENT_FILTERS: Dict[str, Tuple[Callable, EnvironmentFilterDefinition]] = {
    k: (v, EnvironmentFilterDefinition(
        name=k,
        expression=k
    ))
    for k, v in JINJA2_FILTERS.items()
}
