"""Контракты шлюзов к графу, connection'ам, выражениям, SQL и источнику схемы."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from ..catalog_values import (
    DatasetLocator,
    ObservedField,
    ProjectRef,
    SchemaActor,
    SqlTableReferences,
)
from ..graph import ConnectionLocator, ProjectGraphSnapshot, ProjectStampSource
from ..lineage import NodePortTypes, PlannedRuleColumn, SqlLineageResult, SqlSchemaHint


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

    async def node_exists(self, project_id: str, organization_id: str | None, node_id: str) -> bool:
        """Есть ли нода с таким ui_id в неудалённом проекте; без загрузки снэпшота графа."""
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
        locator: DatasetLocator,
        bypass_cache: bool = False,
    ) -> tuple[ObservedField, ...]:
        """Читает актуальную схему источника по его локатору; бросает SchemaSourceUnavailableError."""
        ...


class CatalogProjectSource(Protocol):
    async def list_projects(
        self,
        *,
        lineage_schema_version: int,
        stale_only: bool,
        after_project_id: str | None,
        limit: int,
        organization_id: str | None = None,
        project_ids: Sequence[str] | None = None,
    ) -> list[ProjectRef]:
        """Неудалённые проекты, упорядоченные по project_id, keyset-страница после after_project_id.

        stale_only=True оставляет проекты без проекции, с lineage_schema_version меньше переданной
        или с graph_revision проекции, не совпадающим с graph_revision проекта.
        """
        ...


class NodePortTypeGateway(Protocol):
    def get_port_types(self, node_name: str) -> NodePortTypes | None:
        """Типы портов ноды по имени класса; None, если нода неизвестна реестру."""
        ...


class SqlColumnLineageExtractor(Protocol):
    def extract(
        self,
        sql: str,
        dialect: str,
        project_variables: Mapping[str, Any],
        schema: SqlSchemaHint,
    ) -> SqlLineageResult:
        """Колонки результата запроса и их источники; неразбираемый SQL даёт supported=False."""
        ...


class ColumnRulePlanner(Protocol):
    def plan(
        self,
        operation: str,
        rules: Sequence[Mapping[str, Any]],
        columns: Sequence[str],
    ) -> tuple[PlannedRuleColumn, ...] | None:
        """Статический план column_rules; None, если план зависит от данных или правила невалидны."""
        ...


class LineageTextRenderer(Protocol):
    def render(self, template_key: str, params: Mapping[str, Any], locale: str) -> str | None: ...
