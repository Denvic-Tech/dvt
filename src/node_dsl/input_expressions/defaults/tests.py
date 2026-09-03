from collections.abc import Callable

from jinja2.tests import TESTS as JINJA2_TESTS

from src.node_dsl.input_expressions.types import EnvironmentTestDefinition

DEFAULT_ENVIRONMENT_TESTS: dict[str, tuple[Callable, EnvironmentTestDefinition]] = {
    **{
        name: (
            _callable,
            EnvironmentTestDefinition(
                name=name,
                expression=name,
                description=f"'{name}' test.",
            ),
        )
        for name, _callable in JINJA2_TESTS.items()
    },
    "True": (
        JINJA2_TESTS["true"],
        EnvironmentTestDefinition(
            name="True",
            expression="True",
            description="'true' test alias.",
        )
    )  # TODO: Better implement alias system
}
