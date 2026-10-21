"""Статический план column_rules через `build_plan` Node DSL на пустом DataFrame."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...domain import ColumnRulePlanner, PlannedRuleColumn


class NodeDslColumnRulePlanner(ColumnRulePlanner):
    def plan(
        self,
        operation: str,
        rules: Sequence[Mapping[str, Any]],
        columns: Sequence[str],
    ) -> tuple[PlannedRuleColumn, ...] | None:
        try:
            import pandas as pd

            from src.node_dsl.node_mixins.column_rules import ColumnRule, build_plan
            from src.nodes.transform._shared.column_rules import OPERATIONS
        except Exception:
            return None

        definition = OPERATIONS.get(operation)
        if definition is None:
            return None
        try:
            parsed = [ColumnRule.model_validate(rule) for rule in rules]
        except Exception:
            return None
        # Селекторы по типу колонок и runtime-привязки зависят от данных: статически не планируются.
        if any(rule.selector.types or rule.input_bindings for rule in parsed if rule.enabled):
            return None

        frame = pd.DataFrame({name: pd.Series(dtype="object") for name in columns})
        try:
            planned = build_plan(frame, list(rules), definition)
        except Exception:
            return None

        result: list[PlannedRuleColumn] = []
        for item in planned:
            drops_source = bool(definition.drops_source(item.params)) if definition.drops_source else False
            result.append(
                PlannedRuleColumn(
                    source=item.source,
                    targets=tuple(item.targets),
                    drops_source=drops_source,
                    expression=getattr(item.params, "expression", None),
                )
            )
        return tuple(result)
