from __future__ import annotations

import keyword

from .types import ExpressionPolicy, ExpressionPolicyRef
from .constants import RESERVED_VARIABLE_NAMES
from .defaults import DEFAULT_EXPRESSION_POLICY


def resolve_expression_policy(policy: ExpressionPolicyRef) -> ExpressionPolicy:
    if policy is None or policy == DEFAULT_EXPRESSION_POLICY.name:
        return DEFAULT_EXPRESSION_POLICY
    if isinstance(policy, ExpressionPolicy):
        return policy
    raise ValueError(f"Unknown expression policy '{policy}'.")


def get_expression_policy_name(policy: ExpressionPolicyRef) -> str:
    return resolve_expression_policy(policy).name


def is_safe_expression_variable_name(name: str) -> bool:
    return (
            isinstance(name, str)
            and name.isidentifier()
            and not keyword.iskeyword(name)
            and name not in RESERVED_VARIABLE_NAMES
    )
