from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.node_dsl.input_expressions import (
    get_default_expression_policy,
    get_registered_expression_filters,
    get_registered_expression_globals,
    get_registered_expression_tests,
)
from src.node_dsl.input_expressions.types import (
    EnvironmentFilterDefinition,
    EnvironmentTestDefinition,
    EnvironmentGlobalDefinition,
    ExpressionPolicy
)

r = router = APIRouter()


class ExpressionsConfig(BaseModel):
    filters: list[EnvironmentFilterDefinition] = Field(default_factory=list)
    tests: list[EnvironmentTestDefinition] = Field(default_factory=list)
    globals: list[EnvironmentGlobalDefinition] = Field(default_factory=list)
    default_policy: ExpressionPolicy


@router.get("/expressions", response_model=ExpressionsConfig)
async def get_expressions_config() -> ExpressionsConfig:
    return ExpressionsConfig(
        filters=get_registered_expression_filters(),
        tests=get_registered_expression_tests(),
        globals=get_registered_expression_globals(),
        default_policy=get_default_expression_policy(),
    )
