from ..constants import IMMUTABLE_INPUT_VARIABLES_SYSTEM_ATTRIBUTES_RULE
from ..types import ExpressionPolicy
from .filters import DEFAULT_ENVIRONMENT_FILTERS
from .globals import DEFAULT_ENVIRONMENT_GLOBALS
from .tests import DEFAULT_ENVIRONMENT_TESTS

DEFAULT_EXPRESSION_POLICY: ExpressionPolicy = ExpressionPolicy(
    name="default",
    allowed_filters=frozenset(DEFAULT_ENVIRONMENT_FILTERS.keys()),
    allowed_tests=frozenset(DEFAULT_ENVIRONMENT_TESTS.keys()),
    allowed_globals=frozenset(DEFAULT_ENVIRONMENT_GLOBALS.keys()),
    allowed_attribute_rules=frozenset(
        {IMMUTABLE_INPUT_VARIABLES_SYSTEM_ATTRIBUTES_RULE}
    ),
)
