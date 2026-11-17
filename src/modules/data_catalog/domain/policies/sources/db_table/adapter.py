"""Адаптер вида `db_table`: таблицы реляционных БД, адресуемые DB-нодами и SQL."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ....catalog_values import DatasetLocator, ProjectionDiagnostic, RawLocator
from ....exceptions import SourceNotSupportedError
from ....gateways import ExpressionResolver, SqlTableReferenceExtractor
from ....graph import ConnectionLocator, GraphInputValue, ProjectGraphSnapshot
from ....types import DiagnosticReason, LocatorKind, ResolvedVia
from ..contracts import ResolvedLocator, ResolvedLocators
from .locator import DB_TABLE_KIND, DbTableLocator, db_connection_coordinates
from .locator_extraction import LocatorCandidate, extract_locator_candidates
from .physical_key import (
    build_physical_key,
    canonical_dialect,
    describe_db_table,
    normalize_locator,
)
from .sql_tables import select_table_candidates, sql_reference, sql_table_ref_to_raw_locator


class DbTableAdapter:
    kind = DB_TABLE_KIND

    def extract_candidates(
        self,
        snapshot: ProjectGraphSnapshot,
    ) -> tuple[list[LocatorCandidate], list[ProjectionDiagnostic]]:
        return extract_locator_candidates(snapshot)

    def resolve(
        self,
        candidate: LocatorCandidate,
        connection: ConnectionLocator,
        *,
        expressions: ExpressionResolver,
        sql: SqlTableReferenceExtractor,
        project_variables: Mapping[str, Any],
    ) -> ResolvedLocators:
        dialect = canonical_dialect(connection.type)
        if dialect is None:
            raise SourceNotSupportedError(f"connection type {connection.type!r} is not supported")

        resolution = _resolve_raw_locators(
            candidate=candidate,
            dialect=dialect,
            expressions=expressions,
            sql=sql,
            project_variables=project_variables,
        )
        coordinates = db_connection_coordinates(connection)
        locators: list[ResolvedLocator] = []
        diagnostics: list[ProjectionDiagnostic] = []
        for raw, reference in resolution.raw_locators:
            typed = normalize_locator(raw, coordinates, dialect=dialect)
            if not typed.table:
                diagnostics.append(
                    ProjectionDiagnostic(
                        node_id=candidate.node_id,
                        node_name=candidate.node_name,
                        reason=DiagnosticReason.LOCATOR_INPUT_MISSING,
                        detail="empty table name",
                    )
                )
                continue
            locators.append(ResolvedLocator(locator=typed.to_locator(), reference=reference))
        return ResolvedLocators(
            locators=tuple(locators),
            resolved_via=resolution.resolved_via,
            used_variables=resolution.used_variables,
            diagnostics=tuple(diagnostics),
            sql=resolution.sql,
            dialect=dialect,
            column_filter=resolution.column_filter,
        )

    def build_key(self, locator: DatasetLocator) -> str:
        return build_physical_key(DbTableLocator.from_locator(locator))

    def describe(self, locator: DatasetLocator) -> str:
        return describe_db_table(DbTableLocator.from_locator(locator))

    def matches_observation(
        self,
        locator: DatasetLocator,
        parts: Mapping[str, str | None],
    ) -> bool:
        observed_table = parts.get("table")
        if not observed_table:
            return True
        return DbTableLocator.from_locator(locator).table.lower() == observed_table.lower()


@dataclass(frozen=True, slots=True)
class _RawResolution:
    raw_locators: tuple[tuple[RawLocator, str | None], ...]
    resolved_via: ResolvedVia
    used_variables: bool
    sql: str | None = None
    column_filter: tuple[str, ...] | None = None


def _resolve_raw_locators(
    *,
    candidate: LocatorCandidate,
    dialect: str,
    expressions: ExpressionResolver,
    sql: SqlTableReferenceExtractor,
    project_variables: Mapping[str, Any],
) -> _RawResolution:
    spec = candidate.spec
    used_variables = False

    def value_of(name: str) -> Any:
        nonlocal used_variables
        item = candidate.inputs.get(name)
        if item is None:
            return None
        if item.kind == "expr":
            used_variables = True
            return expressions.resolve(
                str(item.value), item.expression_kind or "template", project_variables
            )
        return item.value

    def resolve_sql() -> _RawResolution:
        sql_text = _as_text(value_of(spec.sql_input)) or ""
        references = sql.extract(sql_text, dialect, project_variables)
        tables = select_table_candidates(
            references.tables,
            cte_names=references.cte_names,
            excluded_names=candidate.dataframe_input_names,
        )
        raw = tuple(
            (sql_table_ref_to_raw_locator(ref, dialect=dialect), sql_reference(ref)) for ref in tables
        )
        return _RawResolution(
            raw_locators=raw,
            resolved_via=ResolvedVia.SQL,
            used_variables=used_variables or references.used_project_variables,
            sql=sql_text,
        )

    if candidate.kind is LocatorKind.EXPLICIT:
        raw = RawLocator(
            table=_as_text(value_of(spec.table_input)) or "",
            schema=_as_text(value_of(spec.schema_input)),
            database=_as_text(value_of(spec.database_input)),
        )
        resolved_via = ResolvedVia.EXPRESSION if used_variables else ResolvedVia.CONST
        return _RawResolution(
            raw_locators=((raw, None),),
            resolved_via=resolved_via,
            used_variables=used_variables,
            column_filter=_column_filter(candidate.inputs.get(spec.columns_input)),
        )

    if candidate.kind is LocatorKind.SQL or spec.sql_input in candidate.inputs:
        return resolve_sql()

    manual = value_of(spec.manual_variables_input)
    raw_locators: list[RawLocator] = []
    if isinstance(manual, Mapping):
        for entry in manual.values():
            if not isinstance(entry, Mapping):
                continue
            table = _as_text(entry.get("table_name"))
            if not table:
                continue
            raw_locators.append(
                RawLocator(
                    table=table,
                    schema=_as_text(entry.get("schema_name")),
                    database=_as_text(entry.get("database_name")),
                )
            )
    resolved_via = ResolvedVia.EXPRESSION if used_variables else ResolvedVia.CONST
    return _RawResolution(
        raw_locators=tuple((raw, None) for raw in raw_locators),
        resolved_via=resolved_via,
        used_variables=used_variables,
    )


def _column_filter(value: GraphInputValue | None) -> tuple[str, ...] | None:
    """Константный список колонок Read-ноды; выражение или пустой список означают «все колонки»."""
    if value is None or value.kind != "const" or not isinstance(value.value, (list, tuple)):
        return None
    names = tuple(str(item).strip() for item in value.value if str(item).strip())
    return names or None


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, GraphInputValue):
        value = value.value
    text = str(value).strip()
    return text or None
