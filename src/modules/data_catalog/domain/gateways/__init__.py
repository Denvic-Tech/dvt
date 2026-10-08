"""Контракты шлюзов к графу, connection'ам, выражениям, SQL и источнику схемы."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from ..catalog_values import ObservedField, SchemaActor, SqlTableReferences
from ..graph import ConnectionLocator, ProjectGraphSnapshot, ProjectStampSource


class ProjectGraphGateway(Protocol):
    async def load_stamp_source(
        self,
        project_id: str,
        organization_id: str | None,
    ) -> ProjectStampSource | None:
        """organization_id=None снимает фильтр по организации (глобальный доступ)."""
        ...

    async def load_snapshot(
        self,
        project_id: str,
        organization_id: str,
    ) -> ProjectGraphSnapshot | None: ...

    async def lock_project(self, project_id: str, organization_id: str) -> None:
        """Сериализует пересборки одного проекта; на хранилищах без блокировок — no-op."""
        ...


class ConnectionLocatorGateway(Protocol):
    async def get_locator(
        self,
        connection_id: str,
        organization_id: str,
    ) -> ConnectionLocator | None: ...


class ExpressionResolver(Protocol):
    def resolve(
        self,
        expression: str,
        expression_kind: str,
        project_variables: Mapping[str, Any],
    ) -> Any:
        """Вычисляет expression-значение статически; при невозможности бросает ExpressionUnresolvedError."""
        ...


class SqlTableReferenceExtractor(Protocol):
    def extract(
        self,
        sql: str,
        dialect: str,
        project_variables: Mapping[str, Any],
    ) -> SqlTableReferences:
        """Возвращает таблицы, на которые ссылается SQL; бросает SqlReferenceExtractionError."""
        ...


class DatasetSchemaSource(Protocol):
    async def fetch_fields(
        self,
        *,
        connection_id: str,
        actor: SchemaActor,
        database: str | None,
        schema: str | None,
        table: str,
        bypass_cache: bool = False,
    ) -> tuple[ObservedField, ...]:
        """Читает актуальную схему таблицы; бросает SchemaSourceUnavailableError."""
        ...
