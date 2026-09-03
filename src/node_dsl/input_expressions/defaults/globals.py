from uuid import uuid4

from datetime import datetime, UTC
from typing import Dict, Tuple, Callable

from src.node_dsl.input_expressions.types import EnvironmentGlobalDefinition


DEFAULT_ENVIRONMENT_GLOBALS: Dict[str, Tuple[Callable, EnvironmentGlobalDefinition]] = {
    "len": (len, EnvironmentGlobalDefinition(
        name="len",
        expression="len",
        description="Length of an object",
    )),
    "uuid": (lambda: str(uuid4()), EnvironmentGlobalDefinition(
        name="uuid",
        expression="uuid",
        description="Generate UUID4 string",
    )),
    "now": (datetime.now, EnvironmentGlobalDefinition(
        name="now",
        expression="now",
        description="Current time",
    )),
    "utcnow": (lambda: datetime.now(tz=UTC), EnvironmentGlobalDefinition(
        name="utcnow",
        expression="utcnow",
        description="Current time in UTC",
    ))
}
