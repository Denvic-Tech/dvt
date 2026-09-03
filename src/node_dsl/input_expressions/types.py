from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, Field


class EnvironmentFilterDefinition(BaseModel):
    name: str = Field(..., description="Name of environment filter")
    expression: str = Field(..., description="Expression of environment filter")
    description: str | None = Field(None, description="Description of environment filter")


class EnvironmentGlobalDefinition(BaseModel):
    name: str = Field(..., description="Name of environment global")
    expression: str = Field(..., description="Expression of environment global")
    description: str | None = Field(None, description="Description of environment global")


class EnvironmentTestDefinition(BaseModel):
    name: str = Field(..., description="Name of environment test")
    expression: str = Field(..., description="Expression of environment test")
    description: Optional[str] = Field(None, description="Description of environment test")


@dataclass(frozen=True)
class ExpressionPolicy:
    name: str
    allowed_filters: frozenset[str]
    allowed_globals: frozenset[str] = frozenset()
    allowed_tests: frozenset[str] = frozenset()
    allow_statements: bool = False
    allow_comments: bool = True
    allowed_attribute_rules: frozenset[str] = frozenset()


ExpressionPolicyRef = ExpressionPolicy | Literal["default"] | None
