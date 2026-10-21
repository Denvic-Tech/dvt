"""Роуты column-level lineage проекта: колонки порта ноды и объяснение одной колонки."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, status

from services.gateway.deps.data_catalog import get_data_catalog_use_cases
from services.gateway.deps.project import UserProjectByPath
from services.gateway.utils.detect_locale import detect_locale

from src.db.fastapi.dependencies import AsyncSessionDepends
from src.modules.data_catalog.domain import (
    ExplainDirection,
    LineageColumnNotFoundError,
    LineageNodePortNotFoundError,
)

from .lineage_schemas import explanation_to_schema, node_fields_to_schema
from .schemas import ExplainDirectionLiteral, FieldExplanationSchema, NodeFieldsResponseSchema

router = APIRouter(prefix="/projects/{project_id}/lineage", tags=["Data Catalog"])

XLanguage = Annotated[str | None, Header(alias="X-Language")]
AcceptLanguage = Annotated[str | None, Header(alias="Accept-Language")]


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/nodes/{node_id}/fields", response_model=NodeFieldsResponseSchema)
async def get_node_fields(
    project: UserProjectByPath,
    node_id: str,
    session: AsyncSessionDepends,
    port: Annotated[str | None, Query(max_length=128)] = None,
    x_language: XLanguage = None,
    accept_language: AcceptLanguage = None,
) -> NodeFieldsResponseSchema:
    """Колонки DataFrame-порта ноды с происхождением и наследованными описаниями."""
    use_cases = get_data_catalog_use_cases(session)
    try:
        result = await use_cases.get_node_fields.execute(
            project_id=project.id,
            organization_id=project.organization_id,
            node_id=node_id,
            port=port,
            locale=detect_locale(x_language, accept_language).value,
        )
    except LineageNodePortNotFoundError as exc:
        raise _not_found(exc) from exc
    # Ленивый repair проекции мог пересобрать lineage: фиксируем результат.
    await session.commit()
    return node_fields_to_schema(result)


@router.get("/explain", response_model=FieldExplanationSchema)
async def explain_field(
    project: UserProjectByPath,
    session: AsyncSessionDepends,
    node_id: Annotated[str, Query(min_length=1)],
    column: Annotated[str, Query(min_length=1)],
    port: Annotated[str | None, Query(max_length=128)] = None,
    direction: ExplainDirectionLiteral = "upstream",
    max_depth: Annotated[int, Query(ge=1, le=100)] = 20,
    x_language: XLanguage = None,
    accept_language: AcceptLanguage = None,
) -> FieldExplanationSchema:
    """Путь колонки к источникам (upstream) или к потребителям внутри проекта (downstream)."""
    use_cases = get_data_catalog_use_cases(session)
    try:
        explanation = await use_cases.explain_field.execute(
            project_id=project.id,
            organization_id=project.organization_id,
            node_id=node_id,
            column=column,
            port=port,
            direction=ExplainDirection(direction),
            max_depth=max_depth,
            locale=detect_locale(x_language, accept_language).value,
        )
    except (LineageNodePortNotFoundError, LineageColumnNotFoundError) as exc:
        raise _not_found(exc) from exc
    await session.commit()
    return explanation_to_schema(explanation)
