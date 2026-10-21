from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from services.gateway.deps.data_catalog import (
    build_schema_actor,
    build_viewer,
    get_data_catalog_use_cases,
)
from services.gateway.deps.db_catalog import RedisBytes

from src.db.fastapi.dependencies import AsyncSessionDepends
from src.modules.data_catalog.domain import (
    UNSET,
    Dataset,
    DatasetAccessDeniedError,
    DatasetDetails,
    DatasetField,
    DatasetFieldNotFoundError,
    DatasetNotFoundError,
    DatasetSearchHit,
    DatasetSearchQuery,
    DatasetUsageEntry,
    FieldDescriptionChange,
    FieldRef,
    FieldRenameNotApplicableError,
    InvalidFieldReferenceError,
    LinkDirection,
    RefreshOutcome,
)
from src.modules.data_catalog.domain.policies import (
    compute_freshness,
    effective_dataset_description,
    effective_field_description,
)
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly

import config

from .lineage_schemas import dependent_to_schema
from .schemas import (
    DatasetDescriptionPatchSchema,
    DatasetDetailsSchema,
    DatasetFieldSchema,
    DatasetLocatorSchema,
    DatasetPageSchema,
    DatasetSummarySchema,
    DatasetUsageEntrySchema,
    DatasetUsageResponseSchema,
    DirectionLiteral,
    FieldDependentsResponseSchema,
    FieldRefSchema,
    FieldRenameConfirmSchema,
    RefreshOutcomeSchema,
)

router = APIRouter(prefix="/data-catalog", tags=["Data Catalog"])


def _locator(dataset: Dataset) -> DatasetLocatorSchema:
    return DatasetLocatorSchema(
        kind=dataset.locator.kind,
        location=dataset.location,
        parts=dict(dataset.locator.parts),
    )


def _freshness(dataset: Dataset) -> str:
    return compute_freshness(
        dataset,
        ttl_seconds=config.DATA_CATALOG.SCHEMA_SYNC_TTL_SEC,
        now=datetime.now(UTC),
    ).value


def _dataset_common(dataset: Dataset) -> dict:
    effective, provenance = effective_dataset_description(dataset)
    return {
        "id": dataset.id,
        "organization_id": dataset.organization_id,
        "physical_key": dataset.physical_key,
        "locator": _locator(dataset),
        "description": dataset.description,
        "effective_description": effective,
        "description_provenance": provenance.value,
        "description_updated_by": dataset.description_updated_by,
        "description_updated_at": dataset.description_updated_at,
        "freshness": _freshness(dataset),
        "schema_synced_at": dataset.schema_synced_at,
        "last_check_failed_at": dataset.last_check_failed_at,
        "last_check_error": dataset.last_check_error,
        "last_check_error_kind": (
            dataset.last_check_error_kind.value if dataset.last_check_error_kind else None
        ),
        "observed_at_run": dataset.observed_at_run,
        "updated_at": dataset.updated_at,
    }


def summary_to_schema(hit: DatasetSearchHit) -> DatasetSummarySchema:
    return DatasetSummarySchema(
        **_dataset_common(hit.dataset),
        field_count=hit.field_count,
        reader_count=hit.reader_count,
        writer_count=hit.writer_count,
    )


def field_to_schema(field: DatasetField) -> DatasetFieldSchema:
    effective, provenance = effective_field_description(field)
    return DatasetFieldSchema(
        id=field.id,
        name=field.name,
        dtype=field.dtype,
        nullable=field.nullable,
        ordinal=field.ordinal,
        primary_key=field.primary_key,
        source_comment=field.source_comment,
        description=field.description,
        effective_description=effective,
        description_provenance=provenance.value,
        description_updated_by=field.description_updated_by,
        description_updated_at=field.description_updated_at,
        status=field.status.value,
        first_seen_at=field.first_seen_at,
        last_seen_at=field.last_seen_at,
        observed_via=list(field.observed_via),
    )


def details_to_schema(details: DatasetDetails) -> DatasetDetailsSchema:
    dataset = details.dataset
    return DatasetDetailsSchema(
        **_dataset_common(dataset),
        connection_ids=list(details.connection_ids),
        fields=[field_to_schema(field) for field in details.fields],
        created_at=dataset.created_at,
    )


def usage_to_schema(entry: DatasetUsageEntry) -> DatasetUsageEntrySchema:
    return DatasetUsageEntrySchema(
        project_id=entry.project_id,
        project_name=entry.project_name,
        node_id=entry.node_id,
        node_name=entry.node_name,
        direction=entry.direction.value,
        kind=entry.kind.value,
        resolved_via=entry.resolved_via.value,
        graph_revision=entry.graph_revision,
        updated_at=entry.updated_at,
    )


def refresh_to_schema(outcome: RefreshOutcome) -> RefreshOutcomeSchema:
    return RefreshOutcomeSchema(
        status=outcome.status,
        new=outcome.new,
        missing=outcome.missing,
        type_changed=outcome.type_changed,
        affected_project_ids=list(outcome.affected_project_ids),
        error=outcome.error,
        error_kind=outcome.error_kind.value if outcome.error_kind else None,
    )


def field_ref_from_schema(ref: FieldRefSchema) -> FieldRef:
    return FieldRef(field_id=ref.field_id, name=ref.name)


def _not_found(dataset_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Dataset {dataset_id} was not found or is not accessible.",
    )


def _unprocessable(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("/datasets", response_model=DatasetPageSchema)
async def search_datasets(
    user: UserAccessOnly,
    session: AsyncSessionDepends,
    query: Annotated[str | None, Query(max_length=512)] = None,
    connection_id: str | None = None,
    project_id: str | None = None,
    kind: Annotated[str | None, Query(max_length=64)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DatasetPageSchema:
    use_cases = get_data_catalog_use_cases(session)
    page = await use_cases.search.execute(
        viewer=build_viewer(user),
        query=DatasetSearchQuery(
            text=query,
            connection_id=connection_id,
            project_id=project_id,
            kind=kind,
            cursor=cursor,
            limit=limit,
        ),
    )
    # Поиск по project_id может пересобрать проекцию проекта, поэтому фиксируем результат.
    await session.commit()
    return DatasetPageSchema(
        items=[summary_to_schema(hit) for hit in page.items],
        next_cursor=page.next_cursor,
    )


@router.get("/datasets/{dataset_id}", response_model=DatasetDetailsSchema)
async def get_dataset(
    dataset_id: str,
    user: UserAccessOnly,
    session: AsyncSessionDepends,
    redis: RedisBytes,
    include_fields: bool = True,
    sync: bool = True,
) -> DatasetDetailsSchema:
    use_cases = get_data_catalog_use_cases(session, redis)
    try:
        details = await use_cases.get_dataset.execute(
            dataset_id=dataset_id,
            viewer=build_viewer(user),
            actor=build_schema_actor(user),
            include_fields=include_fields,
            sync=sync,
        )
    except (DatasetNotFoundError, DatasetAccessDeniedError) as exc:
        raise _not_found(dataset_id) from exc
    await session.commit()
    return details_to_schema(details)


@router.get("/datasets/{dataset_id}/usage", response_model=DatasetUsageResponseSchema)
async def get_dataset_usage(
    dataset_id: str,
    user: UserAccessOnly,
    session: AsyncSessionDepends,
    direction: DirectionLiteral | None = None,
) -> DatasetUsageResponseSchema:
    use_cases = get_data_catalog_use_cases(session)
    try:
        entries = await use_cases.get_usage.execute(
            dataset_id=dataset_id,
            viewer=build_viewer(user),
            direction=LinkDirection(direction) if direction else None,
        )
    except (DatasetNotFoundError, DatasetAccessDeniedError) as exc:
        raise _not_found(dataset_id) from exc
    await session.commit()
    return DatasetUsageResponseSchema(items=[usage_to_schema(entry) for entry in entries])


@router.get(
    "/datasets/{dataset_id}/fields/{field_id}/dependents",
    response_model=FieldDependentsResponseSchema,
)
async def get_field_dependents(
    dataset_id: str,
    field_id: str,
    user: UserAccessOnly,
    session: AsyncSessionDepends,
    max_depth: Annotated[int, Query(ge=1, le=100)] = 20,
) -> FieldDependentsResponseSchema:
    """Колонки нод во всех видимых проектах, зависящие от поля сущности прямо или транзитивно."""
    use_cases = get_data_catalog_use_cases(session)
    try:
        items = await use_cases.get_field_dependents.execute(
            dataset_id=dataset_id,
            field_id=field_id,
            viewer=build_viewer(user),
            max_depth=max_depth,
        )
    except (DatasetNotFoundError, DatasetAccessDeniedError) as exc:
        raise _not_found(dataset_id) from exc
    except DatasetFieldNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()
    return FieldDependentsResponseSchema(
        dataset_id=dataset_id,
        field_id=field_id,
        items=[dependent_to_schema(item) for item in items],
    )


@router.patch("/datasets/{dataset_id}", response_model=DatasetDetailsSchema)
async def update_dataset_descriptions(
    dataset_id: str,
    body: DatasetDescriptionPatchSchema,
    user: UserAccessOnly,
    session: AsyncSessionDepends,
) -> DatasetDetailsSchema:
    """Глобальные описания: пропущенный ключ не меняет значение, явный null очищает."""
    payload = body.model_dump(exclude_unset=True)
    description = payload.get("description", UNSET)
    viewer = build_viewer(user)
    use_cases = get_data_catalog_use_cases(session)
    try:
        changes = tuple(
            FieldDescriptionChange(
                description=item.description,
                field_id=item.field_id,
                name=item.name,
            )
            for item in body.fields or ()
        )
        await use_cases.set_descriptions.execute(
            dataset_id=dataset_id,
            viewer=viewer,
            actor_user_id=user.id,
            description=description,
            fields=changes,
        )
        details = await use_cases.get_dataset.execute(
            dataset_id=dataset_id,
            viewer=viewer,
            include_fields=True,
            sync=False,
        )
    except (DatasetNotFoundError, DatasetAccessDeniedError) as exc:
        raise _not_found(dataset_id) from exc
    except (DatasetFieldNotFoundError, InvalidFieldReferenceError) as exc:
        raise _unprocessable(exc) from exc
    await session.commit()
    return details_to_schema(details)


@router.post("/datasets/{dataset_id}/refresh", response_model=RefreshOutcomeSchema)
async def refresh_dataset(
    dataset_id: str,
    user: UserAccessOnly,
    session: AsyncSessionDepends,
    redis: RedisBytes,
) -> RefreshOutcomeSchema:
    """Принудительно перечитывает схему из источника; неудача возвращается статусом, не ошибкой."""
    use_cases = get_data_catalog_use_cases(session, redis)
    assert use_cases.refresh_schema is not None
    try:
        outcome = await use_cases.refresh_schema.execute(
            dataset_id=dataset_id,
            viewer=build_viewer(user),
            actor=build_schema_actor(user),
        )
    except (DatasetNotFoundError, DatasetAccessDeniedError) as exc:
        raise _not_found(dataset_id) from exc
    await session.commit()
    return refresh_to_schema(outcome)


@router.post("/datasets/{dataset_id}/fields/rename-confirm", response_model=DatasetDetailsSchema)
async def confirm_field_rename(
    dataset_id: str,
    body: FieldRenameConfirmSchema,
    user: UserAccessOnly,
    session: AsyncSessionDepends,
) -> DatasetDetailsSchema:
    viewer = build_viewer(user)
    use_cases = get_data_catalog_use_cases(session)
    try:
        await use_cases.confirm_rename.execute(
            dataset_id=dataset_id,
            viewer=viewer,
            missing=field_ref_from_schema(body.missing),
            new=field_ref_from_schema(body.new),
        )
        details = await use_cases.get_dataset.execute(
            dataset_id=dataset_id,
            viewer=viewer,
            include_fields=True,
            sync=False,
        )
    except (DatasetNotFoundError, DatasetAccessDeniedError) as exc:
        raise _not_found(dataset_id) from exc
    except (
        DatasetFieldNotFoundError,
        InvalidFieldReferenceError,
        FieldRenameNotApplicableError,
    ) as exc:
        raise _unprocessable(exc) from exc
    await session.commit()
    return details_to_schema(details)
