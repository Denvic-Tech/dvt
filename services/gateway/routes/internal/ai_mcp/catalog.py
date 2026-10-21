"""MCP-обёртки Data Catalog: те же use cases, что и публичные роуты, плюс scope токена."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.deps.data_catalog import (
    build_schema_actor,
    build_viewer,
    get_data_catalog_use_cases,
)
from services.gateway.routes.data_catalog.impl import (
    details_to_schema,
    refresh_to_schema,
    summary_to_schema,
    usage_to_schema,
)
from services.gateway.routes.data_catalog.lineage_schemas import (
    dependent_to_schema,
    explanation_to_schema,
    node_fields_to_schema,
)

from src.modules.ai_mcp_access.domain import ResourceScopeMode
from src.modules.data_catalog.domain import (
    UNSET,
    CatalogViewer,
    DatasetFieldNotFoundError,
    DatasetNotFoundError,
    DatasetSearchQuery,
    ExplainDirection,
    FieldDescriptionChange,
    FieldRef,
    FieldRenameNotApplicableError,
    InvalidFieldReferenceError,
    LinkDirection,
)
from src.modules.data_catalog.infra import (
    SQLAlchemyDatasetConnectionRepository,
    SQLAlchemyDatasetLinkRepository,
)

from .access import get_accessible_project
from .auth import MCPPrincipal
from .errors import AIMCPHTTPError, denied

MAX_LIMIT = 200


def _token_sees_everything(principal: MCPPrincipal) -> bool:
    scope = principal.token.access_scope
    return (
        scope.projects.mode is ResourceScopeMode.ALL
        or scope.db_connections.mode is ResourceScopeMode.ALL
    )


async def _token_can_see_dataset(
    *,
    principal: MCPPrincipal,
    session: AsyncSession,
    viewer: CatalogViewer,
    dataset_id: str,
) -> bool:
    if _token_sees_everything(principal):
        return True
    project_ids = await SQLAlchemyDatasetLinkRepository(session).list_project_ids(dataset_id, viewer)
    if any(principal.allows_project(project_id) for project_id in project_ids):
        return True
    connections = await SQLAlchemyDatasetConnectionRepository(session).list_for_dataset(dataset_id)
    return any(principal.allows_connection(item.connection_id) for item in connections)


async def search_datasets(
    *,
    principal: MCPPrincipal,
    session: AsyncSession,
    query: str | None = None,
    connection_id: str | None = None,
    project_id: str | None = None,
    kind: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    if project_id is not None and not principal.allows_project(project_id):
        raise denied("project")
    if connection_id is not None and not principal.allows_connection(connection_id):
        raise denied("connection")
    if not isinstance(limit, int) or limit < 1 or limit > MAX_LIMIT:
        raise AIMCPHTTPError(422, "INVALID_ARGUMENTS", f"limit must be between 1 and {MAX_LIMIT}.")

    viewer = build_viewer(principal.user)
    use_cases = get_data_catalog_use_cases(session)
    page = await use_cases.search.execute(
        viewer=viewer,
        query=DatasetSearchQuery(
            text=query,
            connection_id=connection_id,
            project_id=project_id,
            kind=kind,
            cursor=cursor,
            limit=limit,
        ),
    )

    items = []
    for hit in page.items:
        if not await _token_can_see_dataset(
            principal=principal, session=session, viewer=viewer, dataset_id=hit.dataset.id
        ):
            continue
        items.append(summary_to_schema(hit).model_dump(mode="json", by_alias=True))
    return {"items": items, "next_cursor": page.next_cursor}


async def get_dataset(
    *,
    principal: MCPPrincipal,
    session: AsyncSession,
    redis: Redis,
    dataset_id: str,
    include_fields: bool = True,
) -> dict[str, Any]:
    viewer = build_viewer(principal.user)
    if not await _token_can_see_dataset(
        principal=principal, session=session, viewer=viewer, dataset_id=dataset_id
    ):
        raise denied("dataset")

    use_cases = get_data_catalog_use_cases(session, redis)
    try:
        details = await use_cases.get_dataset.execute(
            dataset_id=dataset_id,
            viewer=viewer,
            actor=build_schema_actor(principal.user),
            include_fields=bool(include_fields),
            sync=True,
        )
    except DatasetNotFoundError as exc:
        raise denied("dataset") from exc
    return details_to_schema(details).model_dump(mode="json", by_alias=True)


async def get_dataset_usage(
    *,
    principal: MCPPrincipal,
    session: AsyncSession,
    dataset_id: str,
    direction: str | None = None,
) -> dict[str, Any]:
    if direction is not None and direction not in {item.value for item in LinkDirection}:
        raise AIMCPHTTPError(422, "INVALID_ARGUMENTS", "direction must be 'read' or 'write'.")

    viewer = build_viewer(principal.user)
    if not await _token_can_see_dataset(
        principal=principal, session=session, viewer=viewer, dataset_id=dataset_id
    ):
        raise denied("dataset")

    use_cases = get_data_catalog_use_cases(session)
    try:
        entries = await use_cases.get_usage.execute(
            dataset_id=dataset_id,
            viewer=viewer,
            direction=LinkDirection(direction) if direction else None,
        )
    except DatasetNotFoundError as exc:
        raise denied("dataset") from exc
    return {
        "items": [
            usage_to_schema(entry).model_dump(mode="json")
            for entry in entries
            if principal.allows_project(entry.project_id)
        ]
    }


class _FieldRefArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_id: str | None = Field(default=None, min_length=1)
    name: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _exactly_one(self) -> _FieldRefArguments:
        if (self.field_id is None) == (self.name is None):
            raise ValueError("Exactly one of field_id or name must be provided.")
        return self


class _FieldDescriptionArguments(_FieldRefArguments):
    description: str | None = Field(max_length=20480)


class _SetDatasetDescriptionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1)
    description: str | None = Field(default=None, max_length=20480)
    clear_description: bool = False
    fields: list[_FieldDescriptionArguments] | None = None


def _invalid(message: str) -> AIMCPHTTPError:
    return AIMCPHTTPError(422, "INVALID_ARGUMENTS", message)


async def set_dataset_description(
    *,
    principal: MCPPrincipal,
    session: AsyncSession,
    **arguments: Any,
) -> dict[str, Any]:
    """Глобальные описания сущности и полей. Валидируется сырой payload: MCP-клиент
    выбрасывает top-level null, поэтому очистка описания сущности передаётся флагом."""
    try:
        request = _SetDatasetDescriptionArguments.model_validate(arguments)
    except (ValueError, ValidationError) as exc:
        raise _invalid("Dataset description arguments are invalid.") from exc
    if request.clear_description and request.description is not None:
        raise _invalid("clear_description cannot be combined with description.")

    viewer = build_viewer(principal.user)
    if not await _token_can_see_dataset(
        principal=principal, session=session, viewer=viewer, dataset_id=request.dataset_id
    ):
        raise denied("dataset")

    if request.clear_description:
        description: Any = None
    elif "description" in request.model_fields_set:
        description = request.description
    else:
        description = UNSET

    use_cases = get_data_catalog_use_cases(session)
    try:
        await use_cases.set_descriptions.execute(
            dataset_id=request.dataset_id,
            viewer=viewer,
            actor_user_id=principal.user.id,
            description=description,
            fields=tuple(
                FieldDescriptionChange(
                    description=item.description, field_id=item.field_id, name=item.name
                )
                for item in request.fields or ()
            ),
        )
        details = await use_cases.get_dataset.execute(
            dataset_id=request.dataset_id, viewer=viewer, include_fields=True, sync=False
        )
    except DatasetNotFoundError as exc:
        raise denied("dataset") from exc
    except (DatasetFieldNotFoundError, InvalidFieldReferenceError) as exc:
        raise _invalid(str(exc)) from exc
    return details_to_schema(details).model_dump(mode="json", by_alias=True)


async def refresh_dataset(
    *,
    principal: MCPPrincipal,
    session: AsyncSession,
    redis: Redis,
    dataset_id: str,
) -> dict[str, Any]:
    viewer = build_viewer(principal.user)
    if not await _token_can_see_dataset(
        principal=principal, session=session, viewer=viewer, dataset_id=dataset_id
    ):
        raise denied("dataset")

    use_cases = get_data_catalog_use_cases(session, redis)
    assert use_cases.refresh_schema is not None
    try:
        outcome = await use_cases.refresh_schema.execute(
            dataset_id=dataset_id,
            viewer=viewer,
            actor=build_schema_actor(principal.user),
        )
    except DatasetNotFoundError as exc:
        raise denied("dataset") from exc
    return refresh_to_schema(outcome).model_dump(mode="json")


async def confirm_field_rename(
    *,
    principal: MCPPrincipal,
    session: AsyncSession,
    dataset_id: str,
    missing_field: dict[str, Any],
    new_field: dict[str, Any],
) -> dict[str, Any]:
    try:
        missing = _FieldRefArguments.model_validate(missing_field)
        new = _FieldRefArguments.model_validate(new_field)
    except (ValueError, ValidationError) as exc:
        raise _invalid("Field references are invalid.") from exc

    viewer = build_viewer(principal.user)
    if not await _token_can_see_dataset(
        principal=principal, session=session, viewer=viewer, dataset_id=dataset_id
    ):
        raise denied("dataset")

    use_cases = get_data_catalog_use_cases(session)
    try:
        await use_cases.confirm_rename.execute(
            dataset_id=dataset_id,
            viewer=viewer,
            missing=FieldRef(field_id=missing.field_id, name=missing.name),
            new=FieldRef(field_id=new.field_id, name=new.name),
        )
        details = await use_cases.get_dataset.execute(
            dataset_id=dataset_id, viewer=viewer, include_fields=True, sync=False
        )
    except DatasetNotFoundError as exc:
        raise denied("dataset") from exc
    except (
        DatasetFieldNotFoundError,
        InvalidFieldReferenceError,
        FieldRenameNotApplicableError,
    ) as exc:
        raise _invalid(str(exc)) from exc
    return details_to_schema(details).model_dump(mode="json", by_alias=True)


_LOCALES = {"en", "ru", "de"}


def _locale(value: str | None) -> str:
    if value is None:
        return "en"
    lowered = str(value).strip().lower()
    if lowered not in _LOCALES:
        raise AIMCPHTTPError(422, "INVALID_ARGUMENTS", f"locale must be one of {sorted(_LOCALES)}.")
    return lowered


async def get_node_fields(
    *,
    principal: MCPPrincipal,
    session: AsyncSession,
    project_id: str,
    node_id: str,
    port: str | None = None,
    locale: str = "en",
) -> dict[str, Any]:
    project = await get_accessible_project(session, principal, project_id)
    use_cases = get_data_catalog_use_cases(session)
    result = await use_cases.get_node_fields.execute(
        project_id=project.id,
        organization_id=project.organization_id,
        node_id=node_id,
        port=port,
        locale=_locale(locale),
    )
    return node_fields_to_schema(result).model_dump(mode="json")


async def explain_field(
    *,
    principal: MCPPrincipal,
    session: AsyncSession,
    project_id: str,
    node_id: str,
    column: str,
    port: str | None = None,
    direction: str = "upstream",
    max_depth: int = 20,
    locale: str = "en",
) -> dict[str, Any]:
    if direction not in {item.value for item in ExplainDirection}:
        raise AIMCPHTTPError(422, "INVALID_ARGUMENTS", "direction must be 'upstream' or 'downstream'.")
    if not isinstance(max_depth, int) or max_depth < 1 or max_depth > 100:
        raise AIMCPHTTPError(422, "INVALID_ARGUMENTS", "max_depth must be between 1 and 100.")
    project = await get_accessible_project(session, principal, project_id)
    use_cases = get_data_catalog_use_cases(session)
    explanation = await use_cases.explain_field.execute(
        project_id=project.id,
        organization_id=project.organization_id,
        node_id=node_id,
        column=column,
        port=port,
        direction=ExplainDirection(direction),
        max_depth=max_depth,
        locale=_locale(locale),
    )
    return explanation_to_schema(explanation).model_dump(mode="json")


async def get_field_dependents(
    *,
    principal: MCPPrincipal,
    session: AsyncSession,
    dataset_id: str,
    field_id: str,
    max_depth: int = 20,
) -> dict[str, Any]:
    if not isinstance(max_depth, int) or max_depth < 1 or max_depth > 100:
        raise AIMCPHTTPError(422, "INVALID_ARGUMENTS", "max_depth must be between 1 and 100.")
    viewer = build_viewer(principal.user)
    if not await _token_can_see_dataset(
        principal=principal, session=session, viewer=viewer, dataset_id=dataset_id
    ):
        raise denied("dataset")
    use_cases = get_data_catalog_use_cases(session)
    try:
        items = await use_cases.get_field_dependents.execute(
            dataset_id=dataset_id, field_id=field_id, viewer=viewer, max_depth=max_depth
        )
    except DatasetNotFoundError as exc:
        raise denied("dataset") from exc
    return {
        "dataset_id": dataset_id,
        "field_id": field_id,
        "items": [
            dependent_to_schema(item).model_dump(mode="json")
            for item in items
            if principal.allows_project(item.project_id)
        ],
    }
