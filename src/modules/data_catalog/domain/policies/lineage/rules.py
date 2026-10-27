"""Контракт правила ноды для lineage и хелперы, из которых правила собираются.

Правило получает контекст (нода, финализированные порты входов, типы портов) и возвращает
колонки каждого выходного порта. Правила живут в каталоге, а не в классах нод: исходник нод
хеширует кэш исполнения, и правка правила не должна его инвалидировать.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ...gateways import ColumnRulePlanner
from ...graph import GraphNode
from ...lineage import ColumnLineage, LineageRef, NodePortTypes, PortColumns, PortLineage
from ...types import DiagnosticReason, LineageOp, PortStatus


class _Dynamic:
    """Маркер: значение входа задано выражением или связью и статически неизвестно."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "DYNAMIC"


DYNAMIC = _Dynamic()


def is_dynamic(value: Any) -> bool:
    return value is DYNAMIC


@dataclass(slots=True)
class RuleContext:
    node: GraphNode
    inputs: Mapping[str, PortLineage]
    port_types: NodePortTypes
    planner: ColumnRulePlanner | None = None

    def const(self, name: str, default: Any = None) -> Any:
        """Константное значение входа; DYNAMIC для выражений и связей; default, если не задано."""
        value = self.node.inputs.get(name)
        if value is None:
            return self.port_types.defaults.get(name, default)
        if value.kind != "const":
            return DYNAMIC
        return value.value if value.value is not None else self.port_types.defaults.get(name, default)

    def input(self, name: str) -> PortLineage | None:
        return self.inputs.get(name)

    def input_ref(self, input_name: str, column: str) -> LineageRef | None:
        port = self.inputs.get(input_name)
        if port is None or port.column(column) is None:
            return None
        return port.ref(column)


LineageRule = Callable[[RuleContext], Mapping[str, PortColumns]]


class LineageRuleRegistry:
    def __init__(self, rules: Mapping[str, LineageRule] | None = None) -> None:
        self._rules: dict[str, LineageRule] = {}
        for name, rule in (rules or {}).items():
            self.register(name, rule)

    def register(self, node_name: str, rule: LineageRule) -> None:
        if node_name in self._rules:
            raise ValueError(f"lineage rule for {node_name!r} is already registered")
        self._rules[node_name] = rule

    def get(self, node_name: str) -> LineageRule | None:
        return self._rules.get(node_name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._rules)


# --- хелперы ------------------------------------------------------------------------------


def details(template: str, **params: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"template": template}
    payload.update({key: value for key, value in params.items() if value is not None})
    return payload


def pass_column(port: PortLineage, column: ColumnLineage, template: str = "lineage.pass", **params: Any) -> ColumnLineage:
    return ColumnLineage(
        name=column.name,
        op=LineageOp.PASS,
        deps=(port.ref(column.name),),
        details=details(template, **params),
    )


def rename_column(port: PortLineage, source: str, target: str, template: str = "lineage.rename", **params: Any) -> ColumnLineage:
    return ColumnLineage(
        name=target,
        op=LineageOp.RENAME,
        deps=(port.ref(source),),
        details=details(template, source=source, **params),
    )


def compute_column(
    name: str,
    deps: Iterable[LineageRef],
    template: str,
    *,
    deps_unknown: bool = False,
    op: LineageOp = LineageOp.COMPUTE,
    **params: Any,
) -> ColumnLineage:
    return ColumnLineage(
        name=name,
        op=op,
        deps=tuple(deps),
        deps_unknown=deps_unknown,
        details=details(template, **params),
    )


def combine_status(*statuses: PortStatus) -> PortStatus:
    if any(status is PortStatus.UNRESOLVED for status in statuses):
        return PortStatus.PARTIALLY_RESOLVED if any(
            status is not PortStatus.UNRESOLVED for status in statuses
        ) else PortStatus.UNRESOLVED
    if any(status is PortStatus.PARTIALLY_RESOLVED for status in statuses):
        return PortStatus.PARTIALLY_RESOLVED
    return PortStatus.RESOLVED


def propagate(port: PortLineage | None, input_name: str) -> PortColumns | None:
    """Если вход не подключён или неизвестен, выход неизвестен с той же причиной."""
    if port is None:
        return PortColumns.unresolved(DiagnosticReason.LINEAGE_INPUT_MISSING, f"{input_name} is not connected")
    if not port.known:
        return PortColumns.unresolved(
            port.reason or DiagnosticReason.LINEAGE_INPUT_INVALID,
            port.detail or f"{input_name} lineage is unknown",
        )
    return None


def passthrough(
    ctx: RuleContext,
    input_name: str = "df",
    outputs: Iterable[str] = ("output",),
    template: str = "lineage.pass",
    **params: Any,
) -> dict[str, PortColumns]:
    port = ctx.input(input_name)
    blocked = propagate(port, input_name)
    if blocked is not None:
        return dict.fromkeys(outputs, blocked)
    assert port is not None
    columns = tuple(pass_column(port, column, template, **params) for column in port.columns)
    result = PortColumns(columns=columns, status=port.status, reason=port.reason, detail=port.detail)
    return dict.fromkeys(outputs, result)


def dynamic_input(input_name: str) -> dict[str, PortColumns]:
    return {
        "output": PortColumns.unresolved(
            DiagnosticReason.LINEAGE_INPUT_DYNAMIC, f"{input_name} is not a constant"
        )
    }


@dataclass(slots=True)
class ColumnSet:
    """Упорядоченный набор колонок выходного порта с заменой по имени."""

    items: dict[str, ColumnLineage] = field(default_factory=dict)

    @classmethod
    def from_pass(cls, port: PortLineage, template: str = "lineage.pass", **params: Any) -> ColumnSet:
        return cls({column.name: pass_column(port, column, template, **params) for column in port.columns})

    def put(self, column: ColumnLineage) -> None:
        self.items[column.name] = column

    def drop(self, name: str) -> None:
        self.items.pop(name, None)

    def has(self, name: str) -> bool:
        return name in self.items

    def to_port(self, status: PortStatus = PortStatus.RESOLVED, reason: DiagnosticReason | None = None, detail: str | None = None) -> PortColumns:
        return PortColumns(columns=tuple(self.items.values()), status=status, reason=reason, detail=detail)


def as_str_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item is not None]
    return None


def as_str_dict(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    return {str(key): str(item) for key, item in value.items() if item is not None}
