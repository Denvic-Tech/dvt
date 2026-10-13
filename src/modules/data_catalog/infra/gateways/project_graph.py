from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.pipeline_graph.infra.db_models import GraphEdgeRecord, GraphNodeRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.node_dsl.core.input_values import parse_node_input_value
from src.node_dsl.core.input_values.types import (
    NodeInputConstantValue,
    NodeInputExpressionValue,
    NodeInputLinkValue,
)
from src.schemas.internal.project_variables import ProjectVariables

from ...domain import (
    GraphEdge,
    GraphInputValue,
    GraphNode,
    ProjectGraphGateway,
    ProjectGraphSnapshot,
    ProjectStampSource,
)


def to_graph_input_value(raw: Any) -> GraphInputValue:
    """Типизированные значения разбираем, legacy без маркера и неизвестные маркеры считаем const."""
    try:
        parsed = parse_node_input_value(raw)
    except ValueError:
        return GraphInputValue.const(raw)
    if parsed is None:
        return GraphInputValue.const(raw)
    if isinstance(parsed, NodeInputConstantValue):
        return GraphInputValue.const(parsed.value)
    if isinstance(parsed, NodeInputExpressionValue):
        return GraphInputValue.expr(parsed.value, parsed.expression_kind)
    if isinstance(parsed, NodeInputLinkValue):
        return GraphInputValue.link(parsed.node_id, parsed.output_name)
    return GraphInputValue.const(raw)


class SQLAlchemyProjectGraphGateway(ProjectGraphGateway):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_stamp_source(
        self,
        project_id: str,
        organization_id: str | None,
    ) -> ProjectStampSource | None:
        project = await self._select_project(project_id, organization_id)
        if project is None:
            return None
        return self._stamp_source(project)

    async def load_snapshot(
        self,
        project_id: str,
        organization_id: str,
    ) -> ProjectGraphSnapshot | None:
        project = await self._select_project(project_id, organization_id)
        if project is None:
            return None

        node_rows = (
            await self._session.execute(
                sa.select(GraphNodeRecord.ui_id, GraphNodeRecord.name, GraphNodeRecord.input_values)
                .where(GraphNodeRecord.project_id == project_id)
                .order_by(GraphNodeRecord.ui_id)
            )
        ).all()
        edge_rows = (
            await self._session.execute(
                sa.select(
                    GraphEdgeRecord.source,
                    GraphEdgeRecord.target,
                    GraphEdgeRecord.source_handle,
                    GraphEdgeRecord.target_handle,
                ).where(GraphEdgeRecord.project_id == project_id)
            )
        ).all()

        nodes = tuple(
            GraphNode(
                ui_id=ui_id,
                name=name,
                inputs={
                    str(key): to_graph_input_value(value)
                    for key, value in (input_values or {}).items()
                },
            )
            for ui_id, name, input_values in node_rows
        )
        edges = tuple(
            GraphEdge(source=source, target=target, source_handle=source_handle, target_handle=target_handle)
            for source, target, source_handle, target_handle in edge_rows
        )
        return ProjectGraphSnapshot(stamp_source=self._stamp_source(project), nodes=nodes, edges=edges)

    async def lock_project(self, project_id: str, organization_id: str) -> None:
        bind = self._session.get_bind()
        if bind is not None and bind.dialect.name == "sqlite":
            return
        await self._session.execute(
            sa.select(ProjectRecord.id)
            .where(ProjectRecord.id == project_id, ProjectRecord.organization_id == organization_id)
            .with_for_update()
        )

    async def _select_project(
        self,
        project_id: str,
        organization_id: str | None,
    ) -> ProjectRecord | None:
        filters = [ProjectRecord.id == project_id, ProjectRecord.is_deleted.is_(False)]
        if organization_id is not None:
            filters.append(ProjectRecord.organization_id == organization_id)
        statement = sa.select(ProjectRecord).where(*filters)
        return (await self._session.execute(statement)).scalar_one_or_none()

    @staticmethod
    def _stamp_source(project: ProjectRecord) -> ProjectStampSource:
        return ProjectStampSource(
            project_id=project.id,
            organization_id=project.organization_id,
            graph_revision=int(project.graph_revision or 0),
            variables=_raw_project_variables(project.variables),
        )


def _raw_project_variables(stored: Any) -> dict[str, Any] | None:
    """Переменные хранятся как {name: {value, type, ...}}; выражениям нужны только значения."""
    if not stored:
        return None
    try:
        return ProjectVariables(variables=stored).raw_values
    except ValueError:
        return dict(stored) if isinstance(stored, dict) else None
