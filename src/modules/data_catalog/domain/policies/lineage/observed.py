"""Наблюдённый состав колонок порта как второй источник фактов для lineage.

Правило приоритета одно: происхождение всегда из графа; состав колонок из графа, если правило
ноды его знает, иначе из последнего наблюдения воркера. Подстановка допустима только там, где
статический разбор бессилен по природе ноды (произвольный код, pivot, нода без правила, источник
без статической схемы, неподдерживаемый SQL). Неподключённая нода или невалидные параметры это
ошибка графа, наблюдение её не маскирует.
"""

from __future__ import annotations

from collections.abc import Mapping

from ...catalog_values import ObservedPortSchema
from ...lineage import ColumnLineage, LineageRef, PortColumns, PortLineage
from ...types import DiagnosticReason, LineageOp, PortStatus

OBSERVABLE_REASONS: frozenset[DiagnosticReason] = frozenset(
    {
        DiagnosticReason.LINEAGE_INPUT_DYNAMIC,
        DiagnosticReason.LINEAGE_RULE_MISSING,
        DiagnosticReason.LINEAGE_SOURCE_NOT_STATIC,
        DiagnosticReason.LINEAGE_SQL_UNSUPPORTED,
    }
)

OBSERVED_TEMPLATE = "lineage.observed"
ASSUMED_PASS_TEMPLATE = "lineage.pass.observed"


def can_use_observation(result: PortColumns) -> bool:
    return result.status is PortStatus.UNRESOLVED and result.reason in OBSERVABLE_REASONS


def observed_port_columns(
    observation: ObservedPortSchema,
    node_name: str,
    original: PortColumns,
    inputs: Mapping[str, PortLineage] | None = None,
) -> PortColumns:
    """Колонки из наблюдения.

    Колонка, которая под тем же именем есть ровно на одном известном входе, считается прошедшей
    сквозь ноду (`pass` с пометкой «предположительно»: код мог её изменить). Остальные получают
    `op: unknown` без происхождения.
    """
    columns = tuple(
        _observed_column(field.name, node_name, inputs or {})
        for field in observation.columns
    )
    cause = original.detail or (original.reason.value if original.reason else "unknown")
    detail = f"columns observed at run {observation.observed_at.isoformat()}; origin unknown: {cause}"
    return PortColumns(
        columns=columns,
        status=PortStatus.PARTIALLY_RESOLVED,
        reason=DiagnosticReason.LINEAGE_SCHEMA_OBSERVED,
        detail=detail,
    )


def _observed_column(name: str, node_name: str, inputs: Mapping[str, PortLineage]) -> ColumnLineage:
    matches: list[tuple[str, LineageRef]] = [
        (input_name, port.ref(name))
        for input_name, port in sorted(inputs.items())
        if port.known and port.column(name) is not None
    ]
    if len(matches) == 1:
        input_name, dep = matches[0]
        return ColumnLineage(
            name=name,
            op=LineageOp.PASS,
            deps=(dep,),
            deps_unknown=False,
            details={"template": ASSUMED_PASS_TEMPLATE, "node": node_name, "input": input_name, "assumed": True},
        )
    return ColumnLineage(
        name=name,
        op=LineageOp.UNKNOWN,
        deps=(),
        deps_unknown=True,
        details={"template": OBSERVED_TEMPLATE, "node": node_name},
    )
