"""Контракт адаптера вида источника: единственное место, где каталог узнаёт о природе источника."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from ...catalog_values import DatasetLocator, ProjectionDiagnostic
from ...gateways import ExpressionResolver, SqlTableReferenceExtractor
from ...graph import ConnectionLocator, ProjectGraphSnapshot
from ...types import LinkDirection, ResolvedVia


class SourceCandidate(Protocol):
    """Нода графа, адресующая источник этого вида через статически известный connection."""

    @property
    def node_id(self) -> str: ...

    @property
    def node_name(self) -> str: ...

    @property
    def direction(self) -> LinkDirection: ...

    @property
    def connection_id(self) -> str: ...


@dataclass(frozen=True, slots=True)
class ResolvedLocator:
    """Адрес источника плюс имя, под которым он упомянут в SQL (для сопоставления колонок lineage)."""

    locator: DatasetLocator
    reference: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedLocators:
    locators: tuple[ResolvedLocator, ...]
    resolved_via: ResolvedVia
    used_variables: bool = False
    diagnostics: tuple[ProjectionDiagnostic, ...] = ()
    sql: str | None = None
    dialect: str | None = None
    column_filter: tuple[str, ...] | None = None


class SourceKindAdapter(Protocol):
    @property
    def kind(self) -> str: ...

    def extract_candidates(
        self,
        snapshot: ProjectGraphSnapshot,
    ) -> tuple[list[SourceCandidate], list[ProjectionDiagnostic]]: ...

    def resolve(
        self,
        candidate: SourceCandidate,
        connection: ConnectionLocator,
        *,
        expressions: ExpressionResolver,
        sql: SqlTableReferenceExtractor,
        project_variables: Mapping[str, Any],
    ) -> ResolvedLocators:
        """Бросает ExpressionUnresolvedError, SqlReferenceExtractionError, SourceNotSupportedError."""
        ...

    def build_key(self, locator: DatasetLocator) -> str: ...

    def describe(self, locator: DatasetLocator) -> str: ...

    def matches_observation(
        self,
        locator: DatasetLocator,
        parts: Mapping[str, str | None],
    ) -> bool:
        """Относится ли наблюдение прогона (части адреса из ноды) к этой сущности."""
        ...
