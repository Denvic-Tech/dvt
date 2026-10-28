"""Правила встроенных нод: как каждая нода преобразует набор колонок своего DataFrame-входа.

Семантика выведена из `process()` нод (см. план Ф3). Ноды, чей набор колонок зависит от данных
или произвольного кода, честно отдают `unresolved`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from ...gateways import ColumnRulePlanner
from ...lineage import ColumnLineage, LineageRef, PortColumns, PortLineage
from ...types import DiagnosticReason, LineageOp
from .expression_deps import expression_dependencies
from .rules import (
    DYNAMIC,
    ColumnSet,
    LineageRuleRegistry,
    RuleContext,
    as_str_dict,
    as_str_list,
    combine_sides,
    compute_column,
    details,
    dynamic_input,
    is_dynamic,
    pass_column,
    passthrough,
    propagate,
    rename_column,
)

PASSTHROUGH_NODES: tuple[str, ...] = (
    "DataFrameQuery",
    "DataFrameSortValues",
    "DataFrameFillNA",
    "DataFrameCastColumnType",
    "DataFrameNumericNormalizer",
    "DataFrameSetIndex",
)

DYNAMIC_SCHEMA_NODES: dict[str, str] = {
    "DataFramePivot": "pivot columns are produced from data values",
    "DataFrameExecCode": "arbitrary Python code",
    "ConvertVariablesToDataFrame": "columns come from runtime variables",
}

NON_STATIC_SOURCE_NODES: frozenset[str] = frozenset(
    {
        "LoadCSV",
        "LoadExcel",
        "LoadJSON",
        "LoadParquet",
        "ReadKafkaMessages",
        "ReadQueueTopic",
        "HTTPRequest",
    }
)

SINK_NODES: frozenset[str] = frozenset(
    {"WriteDataFrameToDB", "WriteDataFrameToDBV2", "WriteDataFrameToDBV3", "WriteDataFrameToDBV4"}
)

_COLUMN_RULE_OPERATIONS: dict[str, str] = {
    "DataFrameRegexReplace": "regex",
    "DataFrameReplaceValues": "replace",
    "DataFrameSetTimezone": "timezone",
    "DataFrameConvertToPeriodStart": "period",
    "AddTimeDeltaToDataFrame": "delta",
    "DataFrameSplitColumn": "split",
    "DataFrameAddColumnByExpression": "expression",
}


def build_builtin_rules(planner: ColumnRulePlanner | None = None) -> LineageRuleRegistry:
    registry = LineageRuleRegistry()
    for name in PASSTHROUGH_NODES:
        registry.register(name, _passthrough_rule)
    registry.register("DataFrameFilter", _filter_rule)
    registry.register("DataFrameSelectColumns", _select_rule)
    registry.register("DataFrameDropColumns", _drop_rule)
    registry.register("DataFrameRenameColumns", _rename_rule)
    registry.register("DataFrameJoin", _join_rule)
    registry.register("DataFrameGroupByAgg", _group_by_rule)
    registry.register("DataFrameLagColumns", _lag_rule)
    registry.register("DataFrameUnion", _union_rule)
    registry.register("DataFrameUnpivot", _unpivot_rule)
    registry.register("GetCurrentDateTime", _current_datetime_rule)
    registry.register("SetColumnToDataFrame", _set_column_rule)
    for name, reason in DYNAMIC_SCHEMA_NODES.items():
        registry.register(name, _dynamic_schema_rule(reason))
    legacy = {
        "DataFrameRegexReplace": _in_place_legacy("column_to_replace"),
        "DataFrameReplaceValues": _in_place_legacy("column_to_replace"),
        "DataFrameSetTimezone": _in_place_legacy("column"),
        "DataFrameConvertToPeriodStart": _derived_legacy("column", "new_column"),
        "AddTimeDeltaToDataFrame": _derived_legacy("column_with_time", "new_column_with_time"),
        "DataFrameSplitColumn": _split_legacy,
        "DataFrameAddColumnByExpression": _expression_legacy,
    }
    for name, operation in _COLUMN_RULE_OPERATIONS.items():
        registry.register(name, _column_rules_rule(operation, legacy[name], planner))
    return registry


# --- простые правила ---------------------------------------------------------------------


def _passthrough_rule(ctx: RuleContext) -> Mapping[str, PortColumns]:
    return passthrough(ctx, template="lineage.pass", node=ctx.node.name)


def _filter_rule(ctx: RuleContext) -> Mapping[str, PortColumns]:
    return passthrough(ctx, outputs=("output", "inverted_output"), template="lineage.pass.filter")


def _dynamic_schema_rule(reason: str) -> Callable[[RuleContext], Mapping[str, PortColumns]]:
    def rule(ctx: RuleContext) -> Mapping[str, PortColumns]:
        return {
            name: PortColumns.unresolved(DiagnosticReason.LINEAGE_INPUT_DYNAMIC, reason)
            for name in (ctx.port_types.dataframe_outputs or ("output",))
        }

    return rule


def _select_rule(ctx: RuleContext) -> Mapping[str, PortColumns]:
    port = ctx.input("df")
    blocked = propagate(port, "df")
    if blocked is not None:
        return {"output": blocked}
    assert port is not None
    selected = ctx.const("columns")
    if is_dynamic(selected):
        return dynamic_input("columns")
    names = as_str_list(selected)
    if not names:
        return passthrough(ctx, template="lineage.pass", node=ctx.node.name)
    present = {column.name for column in port.columns}
    columns = ColumnSet()
    for name in names:
        if name in present:
            columns.put(pass_column(port, port.column(name), "lineage.pass.select"))  # type: ignore[arg-type]
    return {"output": columns.to_port(port.status, port.reason, port.detail)}


def _drop_rule(ctx: RuleContext) -> Mapping[str, PortColumns]:
    port = ctx.input("df")
    blocked = propagate(port, "df")
    if blocked is not None:
        return {"output": blocked}
    assert port is not None
    dropped = ctx.const("columns")
    if is_dynamic(dropped):
        return dynamic_input("columns")
    to_drop = set(as_str_list(dropped) or ())
    columns = ColumnSet.from_pass(port, "lineage.pass")
    for name in to_drop:
        columns.drop(name)
    return {"output": columns.to_port(port.status, port.reason, port.detail)}


def _rename_rule(ctx: RuleContext) -> Mapping[str, PortColumns]:
    port = ctx.input("df")
    blocked = propagate(port, "df")
    if blocked is not None:
        return {"output": blocked}
    assert port is not None
    mapping_value = ctx.const("mapping")
    if is_dynamic(mapping_value):
        return dynamic_input("mapping")
    mapping = as_str_dict(mapping_value) or {}
    columns = ColumnSet()
    for column in port.columns:
        target = mapping.get(column.name)
        if target and target != column.name:
            columns.put(rename_column(port, column.name, target))
        else:
            columns.put(pass_column(port, column, "lineage.pass"))
    return {"output": columns.to_port(port.status, port.reason, port.detail)}


# --- join / group by / lag / union / unpivot -----------------------------------------------


def _join_rule(ctx: RuleContext) -> Mapping[str, PortColumns]:
    left = ctx.input("left")
    right = ctx.input("right")
    if left is None and right is None:
        return {"output": PortColumns.unresolved(DiagnosticReason.LINEAGE_INPUT_MISSING, "left and right are not connected")}
    how = ctx.const("how", "left")
    left_on = ctx.const("left_on")
    right_on = ctx.const("right_on")
    if is_dynamic(how) or is_dynamic(left_on) or is_dynamic(right_on):
        return dynamic_input("join keys")
    left_keys = as_str_list(left_on) or []
    right_keys = as_str_list(right_on) or []

    columns = ColumnSet()
    left_names: set[str] = set()
    if left is not None and left.known:
        for column in left.columns:
            left_names.add(column.name)
            columns.put(pass_column(left, column, "lineage.pass.join", side="left"))

    if right is not None and right.known:
        key_pairs = dict(zip(right_keys, left_keys, strict=False)) if how != "cross" else {}
        for column in right.columns:
            name = column.name
            paired_left = key_pairs.get(name)
            if paired_left is not None and paired_left == name and left is not None and left.known and name in left_names:
                # Одноимённые ключи pandas схлопывает в одну колонку: это слияние двух родителей.
                deps: tuple[LineageRef, ...] = (left.ref(name), right.ref(name))
                columns.put(
                    compute_column(name, deps, "lineage.merge.join_key", op=LineageOp.MERGE, left=name, right=name)
                )
                continue
            if (name in left_names and name not in set(right_keys) and name not in set(left_keys)) or (name in left_names and how == "cross"):
                columns.put(rename_column(right, name, f"{name}_right", "lineage.rename.join_suffix", side="right"))
            elif not columns.has(name):
                columns.put(pass_column(right, column, "lineage.pass.join", side="right"))

    status, reason, detail = combine_sides(("left", left), ("right", right))
    return {"output": columns.to_port(status, reason, detail)}


def _group_by_rule(ctx: RuleContext) -> Mapping[str, PortColumns]:
    port = ctx.input("df")
    blocked = propagate(port, "df")
    if blocked is not None:
        return {"output": blocked}
    assert port is not None
    group_by = ctx.const("group_by_columns")
    new_cols = ctx.const("new_cols")
    source_cols = ctx.const("source_cols")
    agg_funcs = ctx.const("agg_funcs")
    if any(is_dynamic(value) for value in (group_by, new_cols, source_cols, agg_funcs)):
        return dynamic_input("aggregation settings")
    keys = as_str_list(group_by) or []
    targets = as_str_list(new_cols) or []
    sources = as_str_list(source_cols) or []
    functions = as_str_list(agg_funcs) or []

    columns = ColumnSet()
    for key in keys:
        source = port.column(key)
        if source is not None:
            columns.put(pass_column(port, source, "lineage.pass.group_key"))
    if targets and len(targets) == len(sources):
        for index, (target, source) in enumerate(zip(targets, sources, strict=False)):
            function = functions[index] if index < len(functions) else None
            ref = port.ref(source) if port.column(source) is not None else None
            columns.put(
                compute_column(
                    target,
                    (ref,) if ref is not None else (),
                    "lineage.aggregate",
                    op=LineageOp.AGGREGATE,
                    deps_unknown=ref is None,
                    function=function,
                    source=source,
                )
            )
    elif targets:
        return {
            "output": PortColumns.unresolved(
                DiagnosticReason.LINEAGE_INPUT_INVALID, "new_cols and source_cols differ in length"
            )
        }
    return {"output": columns.to_port(port.status, port.reason, port.detail)}


def _lag_rule(ctx: RuleContext) -> Mapping[str, PortColumns]:
    port = ctx.input("df")
    blocked = propagate(port, "df")
    if blocked is not None:
        return {"output": blocked}
    assert port is not None
    lagged = ctx.const("columns_to_lag")
    steps = ctx.const("lag_steps", 1)
    if is_dynamic(lagged) or is_dynamic(steps):
        return dynamic_input("lag settings")
    try:
        steps_value = int(steps if steps is not None else 1)
    except (TypeError, ValueError):
        return {"output": PortColumns.unresolved(DiagnosticReason.LINEAGE_INPUT_INVALID, "lag_steps is not an integer")}
    sign = "-" if steps_value < 0 else ""
    columns = ColumnSet.from_pass(port, "lineage.pass")
    for name in as_str_list(lagged) or []:
        if port.column(name) is None:
            continue
        target = f"{name}_lag{sign}{abs(steps_value)}"
        columns.put(compute_column(target, (port.ref(name),), "lineage.compute.lag", source=name, steps=steps_value))
    return {"output": columns.to_port(port.status, port.reason, port.detail)}


def _union_rule(ctx: RuleContext) -> Mapping[str, PortColumns]:
    first = ctx.input("df1")
    second = ctx.input("df2")
    if first is None and second is None:
        return {"output": PortColumns.unresolved(DiagnosticReason.LINEAGE_INPUT_MISSING, "df1 and df2 are not connected")}
    mapping_value = ctx.const("column_mapping")
    if is_dynamic(mapping_value):
        return dynamic_input("column_mapping")
    mapping = as_str_dict(mapping_value) or {}
    right_to_left = {right: left for left, right in mapping.items()}

    columns = ColumnSet()
    if first is not None and first.known:
        for column in first.columns:
            columns.put(pass_column(first, column, "lineage.pass.union", side="df1"))
    if second is not None and second.known:
        for column in second.columns:
            target = right_to_left.get(column.name, column.name)
            existing = columns.items.get(target)
            if existing is not None:
                columns.put(
                    compute_column(
                        target,
                        (*existing.deps, second.ref(column.name)),
                        "lineage.merge.union",
                        op=LineageOp.MERGE,
                        count=2,
                    )
                )
            elif target != column.name:
                columns.put(rename_column(second, column.name, target, "lineage.rename.union", side="df2"))
            else:
                columns.put(pass_column(second, column, "lineage.pass.union", side="df2"))
    status, reason, detail = combine_sides(("df1", first), ("df2", second))
    return {"output": columns.to_port(status, reason, detail)}


def _unpivot_rule(ctx: RuleContext) -> Mapping[str, PortColumns]:
    port = ctx.input("df")
    blocked = propagate(port, "df")
    if blocked is not None:
        return {"output": blocked}
    assert port is not None
    index_value = ctx.const("index_columns")
    long_value = ctx.const("columns_to_long")
    names_column = ctx.const("new_column_name_with_names", "variable")
    values_column = ctx.const("new_column_name_with_values", "value")
    if any(is_dynamic(value) for value in (index_value, long_value, names_column, values_column)):
        return dynamic_input("unpivot settings")
    index_columns = as_str_list(index_value) or []
    melted = as_str_list(long_value) or [c.name for c in port.columns if c.name not in index_columns]
    columns = ColumnSet()
    for name in index_columns:
        source = port.column(name)
        if source is not None:
            columns.put(pass_column(port, source, "lineage.pass"))
    deps = tuple(port.ref(name) for name in melted if port.column(name) is not None)
    columns.put(compute_column(str(names_column), deps, "lineage.compute.unpivot.names", count=len(deps)))
    columns.put(compute_column(str(values_column), deps, "lineage.compute.unpivot.values", count=len(deps)))
    return {"output": columns.to_port(port.status, port.reason, port.detail)}


def _current_datetime_rule(ctx: RuleContext) -> Mapping[str, PortColumns]:
    port = ctx.input("df")
    blocked = propagate(port, "df")
    if blocked is not None:
        return {"output": blocked}
    assert port is not None
    name = ctx.const("column_name")
    if is_dynamic(name):
        return dynamic_input("column_name")
    columns = ColumnSet.from_pass(port, "lineage.pass")
    if name:
        columns.put(compute_column(str(name), (), "lineage.compute.constant", value="current timestamp"))
    return {"output": columns.to_port(port.status, port.reason, port.detail)}


def _set_column_rule(ctx: RuleContext) -> Mapping[str, PortColumns]:
    port = ctx.input("df")
    blocked = propagate(port, "df")
    if blocked is not None:
        return {"output": blocked}
    assert port is not None
    bindings = ctx.const("column_bindings")
    name = ctx.const("column_name")
    if is_dynamic(bindings) or is_dynamic(name):
        return dynamic_input("column settings")
    columns = ColumnSet.from_pass(port, "lineage.pass")
    targets: list[str] = []
    if isinstance(bindings, list):
        for entry in bindings:
            if isinstance(entry, Mapping) and entry.get("target"):
                targets.append(str(entry["target"]))
    elif name:
        targets.append(str(name))
    for target in targets:
        # Источник — Series-порт column_data, его происхождение каталог статически не моделирует.
        columns.put(compute_column(target, (), "lineage.compute.column_input", deps_unknown=True, port="column_data"))
    return {"output": columns.to_port(port.status, port.reason, port.detail)}


# --- column_rules и legacy-режимы ----------------------------------------------------------

LegacyRule = Callable[[RuleContext, PortLineage], PortColumns]


def _column_rules_rule(
    operation: str,
    legacy: LegacyRule,
    planner: ColumnRulePlanner | None,
) -> Callable[[RuleContext], Mapping[str, PortColumns]]:
    def rule(ctx: RuleContext) -> Mapping[str, PortColumns]:  # noqa: PLR0911 - ранние выходы по видам сбоя
        port = ctx.input("df")
        blocked = propagate(port, "df")
        if blocked is not None:
            return {"output": blocked}
        assert port is not None
        rules_value = ctx.const("column_rules")
        if is_dynamic(rules_value):
            return dynamic_input("column_rules")
        if not rules_value:
            return {"output": legacy(ctx, port)}
        active_planner = ctx.planner or planner
        if active_planner is None:
            return {"output": PortColumns.unresolved(DiagnosticReason.LINEAGE_RULE_MISSING, "column_rules planner is unavailable")}
        if not isinstance(rules_value, list):
            return {"output": PortColumns.unresolved(DiagnosticReason.LINEAGE_INPUT_INVALID, "column_rules is not a list")}
        planned = active_planner.plan(operation, rules_value, port.names)
        if planned is None:
            return {"output": PortColumns.unresolved(DiagnosticReason.LINEAGE_INPUT_DYNAMIC, "column_rules depend on data types or runtime bindings")}
        columns = ColumnSet.from_pass(port, "lineage.pass")
        for item in planned:
            source_ref = port.ref(item.source) if port.column(item.source) is not None else None
            for target in item.targets:
                columns.put(_rule_target(port, operation, item.source, source_ref, target, item.expression))
            if item.drops_source:
                columns.drop(item.source)
        return {"output": columns.to_port(port.status, port.reason, port.detail)}

    return rule


def _rule_target(
    port: PortLineage,
    operation: str,
    source: str,
    source_ref: LineageRef | None,
    target: str,
    expression: str | None,
) -> ColumnLineage:
    if operation == "expression":
        deps, failed = expression_dependencies(expression or "", port.names)
        column = compute_column(
            target,
            tuple(port.ref(name) for name in deps),
            "lineage.compute.expression",
            deps_unknown=failed,
            expression=expression,
        )
    elif target == source and source_ref is not None:
        column = ColumnLineage(
            name=target,
            op=LineageOp.PASS,
            deps=(source_ref,),
            details=details("lineage.pass.transformed", operation=operation),
        )
    else:
        column = compute_column(
            target,
            (source_ref,) if source_ref is not None else (),
            "lineage.compute.rule",
            deps_unknown=source_ref is None,
            operation=operation,
            source=source,
        )
    return column


def _in_place_legacy(column_input: str) -> LegacyRule:
    def legacy(ctx: RuleContext, port: PortLineage) -> PortColumns:
        name = ctx.const(column_input)
        if is_dynamic(name):
            return PortColumns.unresolved(DiagnosticReason.LINEAGE_INPUT_DYNAMIC, f"{column_input} is not a constant")
        columns = ColumnSet.from_pass(port, "lineage.pass")
        if name and port.column(str(name)) is not None:
            columns.put(
                ColumnLineage(
                    name=str(name),
                    op=LineageOp.PASS,
                    deps=(port.ref(str(name)),),
                    details=details("lineage.pass.transformed", operation=_legacy_operation(ctx)),
                )
            )
        return columns.to_port(port.status, port.reason, port.detail)

    return legacy


def _derived_legacy(column_input: str, target_input: str) -> LegacyRule:
    def legacy(ctx: RuleContext, port: PortLineage) -> PortColumns:
        source = ctx.const(column_input)
        target = ctx.const(target_input)
        if is_dynamic(source) or is_dynamic(target):
            return PortColumns.unresolved(DiagnosticReason.LINEAGE_INPUT_DYNAMIC, f"{column_input} is not a constant")
        columns = ColumnSet.from_pass(port, "lineage.pass")
        if source and port.column(str(source)) is not None:
            operation = _legacy_operation(ctx)
            if target and str(target) != str(source):
                columns.put(
                    compute_column(str(target), (port.ref(str(source)),), "lineage.compute.rule", operation=operation, source=str(source))
                )
            else:
                columns.put(
                    ColumnLineage(
                        name=str(source),
                        op=LineageOp.PASS,
                        deps=(port.ref(str(source)),),
                        details=details("lineage.pass.transformed", operation=operation),
                    )
                )
        return columns.to_port(port.status, port.reason, port.detail)

    return legacy


def _split_legacy(ctx: RuleContext, port: PortLineage) -> PortColumns:
    source = ctx.const("column")
    max_splits = ctx.const("max_splits", 1)
    drop_source = ctx.const("drop_source", False)
    if any(is_dynamic(value) for value in (source, max_splits, drop_source)):
        return PortColumns.unresolved(DiagnosticReason.LINEAGE_INPUT_DYNAMIC, "split settings are not constants")
    columns = ColumnSet.from_pass(port, "lineage.pass")
    if source and port.column(str(source)) is not None:
        try:
            count = int(max_splits if max_splits is not None else 1)
        except (TypeError, ValueError):
            count = 1
        for index in range(count + 1):
            target = f"{source}_{index + 1}"
            columns.put(compute_column(target, (port.ref(str(source)),), "lineage.compute.split", source=str(source), index=index + 1))
        if drop_source:
            columns.drop(str(source))
    return columns.to_port(port.status, port.reason, port.detail)


def _expression_legacy(ctx: RuleContext, port: PortLineage) -> PortColumns:
    calculated = ctx.const("calculated_columns")
    name = ctx.const("column_name")
    expression = ctx.const("expression")
    if any(is_dynamic(value) for value in (calculated, name, expression)):
        return PortColumns.unresolved(DiagnosticReason.LINEAGE_INPUT_DYNAMIC, "expression settings are not constants")
    columns = ColumnSet.from_pass(port, "lineage.pass")
    entries: list[tuple[str, str, bool]] = []
    if isinstance(calculated, list):
        for entry in calculated:
            if not isinstance(entry, Mapping):
                continue
            target = entry.get("name")
            text = entry.get("expression")
            if target and text:
                entries.append((str(target), str(text), bool(entry.get("input_bindings"))))
    elif name and expression:
        entries.append((str(name), str(expression), False))
    for target, text, bound in entries:
        deps, failed = expression_dependencies(text, port.names)
        columns.put(
            compute_column(
                target,
                tuple(port.ref(dep) for dep in deps),
                "lineage.compute.expression",
                deps_unknown=failed or bound,
                expression=text,
            )
        )
    return columns.to_port(port.status, port.reason, port.detail)


def _legacy_operation(ctx: RuleContext) -> str:
    return _COLUMN_RULE_OPERATIONS.get(ctx.node.name, ctx.node.name)


__all__ = [
    "DYNAMIC",
    "DYNAMIC_SCHEMA_NODES",
    "NON_STATIC_SOURCE_NODES",
    "PASSTHROUGH_NODES",
    "SINK_NODES",
    "build_builtin_rules",
]
