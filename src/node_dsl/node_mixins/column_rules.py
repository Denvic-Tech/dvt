"""Persisted selection and first-match planning for column transforms."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

import dask.dataframe as dd
from pydantic import BaseModel, ConfigDict, Field

from src.logger import logger
from src.node_dsl.exceptions import NodeValidationError
from src.node_dsl.field import InputField
from src.node_dsl.node_mixins.base import NodeFieldsMixin

ColumnKind = Literal["text", "number", "datetime", "boolean", "timedelta", "other"]


class RuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ColumnToken(RuleModel):
    kind: Literal["name", "mask", "all"]
    value: str = ""


class ColumnSelector(RuleModel):
    tokens: list[ColumnToken] = Field(default_factory=list)
    types: list[ColumnKind] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    name_regex: str = ""


class RuleOutput(RuleModel):
    mode: Literal["replace", "new"] = "replace"
    suffix: str = ""
    names: dict[str, str] = Field(default_factory=dict)
    target: str | None = None
    fallback_to_source: bool = False
    require_target: bool = False


class ColumnRule(RuleModel):
    id: str
    enabled: bool = True
    selector: ColumnSelector
    params: dict[str, Any] = Field(default_factory=dict)
    output: RuleOutput = Field(default_factory=RuleOutput)
    skip_incompatible: bool = False
    compatibility: Literal["v1"] | None = None
    input_bindings: dict[str, str] = Field(default_factory=dict)


def column_kind(dtype) -> str:
    from core.types.data_type import DataType

    return {
        DataType.STRING: "text",
        DataType.INT: "number",
        DataType.FLOAT: "number",
        DataType.DATETIME: "datetime",
        DataType.BOOLEAN: "boolean",
        DataType.TIMEDELTA: "timedelta",
    }.get(DataType.from_type(dtype), "other")


def mask_matches(mask: str, name: str) -> bool:
    # Only * and ? are special; brackets are literal. Same grammar in DVT UI.
    pattern = re.escape(mask).replace(r"\*", ".*").replace(r"\?", ".")
    return re.fullmatch(pattern, name, flags=re.DOTALL) is not None


def select_columns(df, selector: ColumnSelector, *, allow_empty_name=False) -> list[str]:
    columns = list(df.columns)
    if not selector.tokens:
        raise ValueError("Choose columns or a name mask")
    for token in selector.tokens:
        if token.kind == "name" and token.value not in columns:
            raise ValueError(f"Column '{token.value}' not found")
        if token.kind != "all" and not token.value and not allow_empty_name:
            raise ValueError("Column names and masks must not be empty")
    pattern = re.compile(selector.name_regex) if selector.name_regex else None
    return [
        col
        for col in columns
        if col not in selector.exclude
        and (not selector.types or column_kind(df[col].dtype) in selector.types)
        and (pattern is None or pattern.search(str(col)) is not None)
        and any(
            token.kind == "all"
            or (token.kind == "name" and token.value == col)
            or (token.kind == "mask" and mask_matches(token.value, str(col)))
            for token in selector.tokens
        )
    ]


@dataclass
class PlannedColumn:
    rule: ColumnRule
    source: str
    targets: list[str]
    params: BaseModel


@dataclass(frozen=True)
class ColumnRuleOperation:
    """Node-owned semantics used by the shared selector and execution lifecycle."""

    params_model: type[BaseModel]
    transform: Callable[[dd.DataFrame, PlannedColumn], dict[str, dd.Series]]
    compatible_kinds: tuple[ColumnKind, ...] = ()
    compatibility_kinds: tuple[ColumnKind, ...] = ()
    expanded_targets: Callable[[str, BaseModel], list[str]] | None = None
    drops_source: Callable[[BaseModel], bool] | None = None


def build_plan(df, rules, operation: ColumnRuleOperation) -> list[PlannedColumn]:
    parsed = [ColumnRule.model_validate(rule) for rule in rules]
    legacy_only = all(rule.compatibility == "v1" for rule in parsed)
    if not df.columns.is_unique and not legacy_only:
        raise ValueError("Column rules require unique input column names")
    if not all(isinstance(col, str) for col in df.columns) and not legacy_only:
        raise ValueError("Column rules require string column names")
    if not rules:
        raise ValueError("Add at least one column rule")
    if len({rule.id for rule in parsed}) != len(parsed):
        raise ValueError("Rule identifiers must be unique")
    claimed: set[str] = set()
    written: set[str] = set()
    plan = []
    for rule in parsed:
        if not rule.enabled:
            continue
        try:
            params = (
                operation.params_model.model_construct(**rule.params)
                if rule.compatibility == "v1"
                else operation.params_model.model_validate(rule.params)
            )
            selected = select_columns(
                df, rule.selector, allow_empty_name=rule.compatibility == "v1"
            )
            if not selected:
                logger.warning(f"Column rule '{rule.id}' matches no input columns")
            for source in selected:
                if source in claimed:
                    continue
                claimed.add(source)
                compatible_kinds = (
                    operation.compatibility_kinds
                    if rule.compatibility == "v1"
                    else operation.compatible_kinds
                )
                if compatible_kinds and column_kind(df[source].dtype) not in compatible_kinds:
                    if rule.skip_incompatible:
                        logger.warning(f"Column rule '{rule.id}' skips incompatible '{source}'")
                        continue
                    raise ValueError(
                        f"Column '{source}' requires dtype: {', '.join(compatible_kinds)}"
                    )
                if operation.expanded_targets is not None:
                    if rule.output.mode != "replace":
                        raise ValueError("This operation uses generated result names")
                    targets = operation.expanded_targets(source, params)
                elif rule.output.mode == "new":
                    if rule.output.require_target and rule.output.target is None:
                        raise ValueError("A result column name is required")
                    target = (
                        rule.output.target
                        if rule.output.target is not None
                        else rule.output.names.get(source, source + rule.output.suffix)
                    )
                    if rule.output.fallback_to_source and not target:
                        target = source
                    if not target.strip() and rule.compatibility != "v1":
                        raise ValueError(f"Empty result name for '{source}'")
                    targets = [target]
                else:
                    targets = [source]
                for target in targets:
                    may_replace = (
                        operation.expanded_targets is None
                        and rule.output.mode == "replace"
                        and target == source
                    )
                    if target in written or (
                        target in df.columns
                        and not may_replace
                        and (rule.compatibility != "v1" or operation.expanded_targets is not None)
                    ):
                        raise ValueError(f"Result column '{target}' already exists")
                    written.add(target)
                plan.append(PlannedColumn(rule, source, targets, params))
        except (ValueError, TypeError, re.error, KeyError) as exc:
            raise ValueError(f"Rule '{rule.id}': {exc}") from exc
    return plan


def apply_rules(df, rules, operation: ColumnRuleOperation):
    plan = build_plan(df, rules, operation)
    assignments = {}
    dropped = []
    for item in plan:
        try:
            # Always read the original DataFrame, never another rule's output.
            transformed = operation.transform(df, item)
            assignments.update(transformed)
            if operation.drops_source is not None and operation.drops_source(item.params):
                dropped.append(item.source)
        except Exception as exc:
            raise NodeValidationError(
                f"Rule '{item.rule.id}', column '{item.source}': {exc}"
            ) from exc
    result = df.drop(columns=dropped) if dropped else df
    return result.assign(**assignments)


def resolve_input_bindings(node, entry):
    """Resolve retained expression/link ports without evaluating their values twice."""
    from copy import deepcopy

    payload = deepcopy(entry.model_dump() if isinstance(entry, BaseModel) else entry)
    for path, input_name in payload.pop("input_bindings", {}).items():
        if input_name not in node._input_field_instances:
            raise NodeValidationError(f"Unknown bound input '{input_name}'.")
        value = getattr(node, input_name)
        target = payload
        parts = path.split(".")
        for part in parts[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        target[int(parts[-1]) if isinstance(target, list) else parts[-1]] = value
    return payload


def contract_runtime_inputs(inputs, legacy_inputs, contract_fields):
    """Do not evaluate obsolete ports retained solely for rollback."""
    from src.node_dsl.core.input_values import NodeInputConstantValue, parse_node_input_value

    entries = []
    active = False
    for name in contract_fields:
        raw = inputs.get(name)
        parsed = parse_node_input_value(raw)
        if parsed is not None and not isinstance(parsed, NodeInputConstantValue):
            return inputs  # A dynamically supplied contract cannot be inspected yet.
        value = parsed.value if isinstance(parsed, NodeInputConstantValue) else raw
        if value is not None:
            active = True
            if isinstance(value, list):
                entries.extend(value)
    if not active:
        return inputs
    bound = {
        field
        for entry in entries
        if isinstance(entry, dict)
        for field in entry.get("input_bindings", {}).values()
    }
    return {
        name: value for name, value in inputs.items() if name not in legacy_inputs or name in bound
    }


class ColumnRulesMixin(NodeFieldsMixin):
    """Legacy inputs remain valid; explicit rules take precedence."""

    column_rules: list[ColumnRule] | None = InputField(
        default=None,
        description="Ordered column rules; first matching enabled rule wins.",
        agent_description=(
            "Use selector.tokens with kind name/mask/all. Masks support * and ?. "
            "Types and exclusions narrow the selection. Rules read the original input schema. "
            "Only the first matching enabled rule applies to each column. Omit for legacy inputs."
        ),
    )
    COLUMN_RULE_OPERATION: ClassVar[ColumnRuleOperation]
    LEGACY_REQUIRED: ClassVar[tuple[str, ...]] = ()
    LEGACY_RULE_INPUTS: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def runtime_inputs(cls, inputs):
        return contract_runtime_inputs(
            inputs,
            cls.LEGACY_RULE_INPUTS or cls.LEGACY_REQUIRED,
            ("column_rules", "calculated_columns"),
        )

    def _resolved_column_rules(self):
        return [resolve_input_bindings(self, rule) for rule in self.column_rules]

    async def _base_validate(self):
        await super()._base_validate()
        if self.column_rules is not None:
            try:
                build_plan(self.df, self._resolved_column_rules(), self.COLUMN_RULE_OPERATION)
            except Exception as exc:
                raise NodeValidationError(str(exc)) from exc
        else:
            for name in self.LEGACY_REQUIRED:
                if getattr(self, name, None) is None:
                    raise NodeValidationError(f"Input '{name}' is required without column_rules.")

    def process(self):
        if self.column_rules is None:
            self.process_legacy()
        else:
            self.output = apply_rules(
                self.df, self._resolved_column_rules(), self.COLUMN_RULE_OPERATION
            )
