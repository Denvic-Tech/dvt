from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse

from services.gateway.routes.impl.project import transfer as transfer_impl

from src.clients.scheduler_client import SchedulerClient, get_schedule_client
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.modules.project_transfer.infra.schemas import (
    ExportRequestSchema,
    ImportPreviewSchema,
    ImportResultSchema,
)
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly

router = APIRouter()

SchedulerClientDepends = Annotated[SchedulerClient, Depends(get_schedule_client)]
BundleUpload = Annotated[UploadFile, File(description="Архив проекта (.dvtpkg)")]
ImportPayloadForm = Annotated[
    str | None,
    Form(description="JSON по схеме ImportRequestSchema: режим, цель и решения по импорту"),
]
# The multipart payload is a JSON string, so its schema is not part of the request body model;
# expose it through a vendor extension for generated clients. The model itself is registered in
# components.schemas via services/gateway/openapi.py (included_models).
IMPORT_PAYLOAD_OPENAPI_EXTRA = {"x-dvt-payload-schema": {"$ref": "#/components/schemas/ImportRequestSchema"}}


@router.post(
    "/export",
    response_class=StreamingResponse,
    responses={200: {"content": {transfer_impl.BUNDLE_MEDIA_TYPE: {}}, "description": "Архив .dvtpkg"}},
    summary="Экспортировать проекты и папки в архив",
)
async def export_projects(
    data: ExportRequestSchema,
    session: AsyncSessionDepends,
    user: UserAccessOnly,
    scheduler_client: SchedulerClientDepends,
) -> StreamingResponse:
    return await transfer_impl.export_route_impl(
        data=data,
        session=session,
        user=user,
        scheduler_client=scheduler_client,
    )


@router.post(
    "/import/preview",
    response_model=ImportPreviewSchema,
    summary="Проверить архив перед импортом",
    openapi_extra=IMPORT_PAYLOAD_OPENAPI_EXTRA,
)
async def preview_import(
    session: AsyncSessionDepends,
    user: UserAccessOnly,
    file: BundleUpload,
    payload: ImportPayloadForm = None,
) -> ImportPreviewSchema:
    return await transfer_impl.preview_import_route_impl(
        file=file,
        payload=payload,
        session=session,
        user=user,
    )


@router.post(
    "/import",
    response_model=ImportResultSchema,
    summary="Импортировать архив проектов",
    openapi_extra=IMPORT_PAYLOAD_OPENAPI_EXTRA,
)
async def import_projects(
    session: AsyncSessionDepends,
    user: UserAccessOnly,
    scheduler_client: SchedulerClientDepends,
    file: BundleUpload,
    payload: ImportPayloadForm = None,
) -> ImportResultSchema:
    return await transfer_impl.import_route_impl(
        file=file,
        payload=payload or "",
        session=session,
        user=user,
        scheduler_client=scheduler_client,
    )
