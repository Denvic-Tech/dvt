"""Gateway wiring for project export/import bundles."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import BinaryIO
from urllib.parse import quote

from fastapi import UploadFile
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from src.clients.scheduler_client import SchedulerClient
from src.db import AsyncSession, async_engine
from src.modules.db_connection import build_connection_service
from src.modules.project_transfer.domain.exceptions import BundleTooLargeError, InvalidBundleError
from src.modules.project_transfer.domain.value_objects import TransferActor, TransferWarning
from src.modules.project_transfer.flow.use_cases import (
    DisableExportedSchedulesUseCase,
    ExportBundleUseCase,
    ImportBundleUseCase,
    PreviewImportUseCase,
)
from src.modules.project_transfer.infra import mappers
from src.modules.project_transfer.infra.crypto import PassphraseSecretsCipher
from src.modules.project_transfer.infra.gateways import (
    ConnectionServiceGateway,
    LocalInstanceInfoProvider,
    ProjectSchedulerGateway,
    RegistryNodeTypeCatalog,
)
from src.modules.project_transfer.infra.repositories import (
    SQLProjectTransferReadRepository,
    SQLProjectTransferWriteRepository,
)
from src.modules.project_transfer.infra.schemas import (
    ExportRequestSchema,
    ImportPreviewSchema,
    ImportRequestSchema,
    ImportResultSchema,
)
from src.modules.project_transfer.infra.serialization import read_bundle, write_bundle
from src.modules.user.infra.db_models import UserRecord
from src.modules.user.infra.repositories import SQLAlchemyUserRepository
from src.utils.user_roles import user_has_admin_access, user_has_global_access

import config

BUNDLE_MEDIA_TYPE = "application/zip"
EXPORT_WARNINGS_HEADER = "X-DVT-Export-Warnings"
_STREAM_CHUNK_SIZE = 1024 * 1024


@lru_cache
def _connection_service():
    return build_connection_service(
        engine=async_engine,
        fernet_key=config.SECURITY.FERNET_KEY,
        user_repository_factory=SQLAlchemyUserRepository,
    )


def _actor(user: UserRecord) -> TransferActor:
    return TransferActor(
        user_id=user.id,
        organization_id=user.organization_id,
        is_admin=user_has_admin_access(user),
        has_global_access=user_has_global_access(user),
    )


def _connections_gateway(user: UserRecord) -> ConnectionServiceGateway:
    return ConnectionServiceGateway(_connection_service(), service_actor=user)


def _node_catalog(session: AsyncSession) -> RegistryNodeTypeCatalog:
    return RegistryNodeTypeCatalog(session)


def _instance_info() -> LocalInstanceInfoProvider:
    return LocalInstanceInfoProvider()


async def _read_upload(file: UploadFile) -> bytes:
    limit = config.OTHER.PROJECT_TRANSFER_BUNDLE_MAX_SIZE_BYTES
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_STREAM_CHUNK_SIZE):
        total += len(chunk)
        if total > limit:
            raise BundleTooLargeError(f"Bundle exceeds the upload limit of {limit} bytes")
        chunks.append(chunk)
    if total == 0:
        raise InvalidBundleError("Uploaded bundle is empty")
    return b"".join(chunks)


def _parse_import_payload(payload: str | None) -> ImportRequestSchema:
    if not payload:
        return ImportRequestSchema()
    try:
        return ImportRequestSchema.model_validate_json(payload)
    except ValidationError as exc:
        raise InvalidBundleError(f"Import payload is invalid: {exc.errors()[0].get('msg', 'validation error')}") from exc


def _warnings_header(warnings: list[TransferWarning]) -> str:
    return json.dumps(
        [{"code": w.code.value, "message": w.message, "project_ref": w.project_ref} for w in warnings],
        ensure_ascii=True,
    )


def _content_disposition(file_name: str) -> str:
    ascii_name = file_name.encode("ascii", "ignore").decode("ascii") or "export.dvtpkg"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(file_name)}"


async def _iter_stream(stream: BinaryIO) -> AsyncIterator[bytes]:
    try:
        while chunk := stream.read(_STREAM_CHUNK_SIZE):
            yield chunk
    finally:
        stream.close()


async def export_route_impl(
    *,
    data: ExportRequestSchema,
    session: AsyncSession,
    user: UserRecord,
    scheduler_client: SchedulerClient,
) -> StreamingResponse:
    selection, options = mappers.export_request_to_domain(data)
    actor = _actor(user)
    schedules = ProjectSchedulerGateway(session, scheduler_client)

    result = await ExportBundleUseCase(
        repository=SQLProjectTransferReadRepository(session),
        connections=_connections_gateway(user),
        node_types=_node_catalog(session),
        schedules=schedules,
        cipher=PassphraseSecretsCipher(),
        instance_info=_instance_info(),
    ).execute(selection, options, actor=actor)

    stream = write_bundle(result.bundle)

    warnings = list(result.warnings)
    if options.include_schedule and options.disable_schedule_after_export:
        warnings.extend(
            await DisableExportedSchedulesUseCase(schedules=schedules).execute(
                result.schedule_project_ids,
                actor=actor,
            )
        )

    headers = {"Content-Disposition": _content_disposition(result.file_name)}
    if warnings:
        headers[EXPORT_WARNINGS_HEADER] = _warnings_header(warnings)
    return StreamingResponse(_iter_stream(stream), media_type=BUNDLE_MEDIA_TYPE, headers=headers)


async def preview_import_route_impl(
    *,
    file: UploadFile,
    payload: str | None,
    session: AsyncSession,
    user: UserRecord,
) -> ImportPreviewSchema:
    request = _parse_import_payload(payload)
    target, _decisions = mappers.import_request_to_domain(request)
    bundle = read_bundle(
        await _read_upload(file),
        max_uncompressed_bytes=config.OTHER.PROJECT_TRANSFER_BUNDLE_MAX_UNCOMPRESSED_BYTES,
        with_file_content=False,
    )
    preview = await PreviewImportUseCase(
        repository=SQLProjectTransferWriteRepository(session),
        connections=_connections_gateway(user),
        node_types=_node_catalog(session),
    ).execute(bundle, target, actor=_actor(user))
    return mappers.preview_to_schema(preview)


async def import_route_impl(
    *,
    file: UploadFile,
    payload: str,
    session: AsyncSession,
    user: UserRecord,
    scheduler_client: SchedulerClient,
) -> ImportResultSchema:
    request = _parse_import_payload(payload)
    target, decisions = mappers.import_request_to_domain(request)
    bundle = read_bundle(
        await _read_upload(file),
        max_uncompressed_bytes=config.OTHER.PROJECT_TRANSFER_BUNDLE_MAX_UNCOMPRESSED_BYTES,
    )
    result = await ImportBundleUseCase(
        repository=SQLProjectTransferWriteRepository(session),
        connections=_connections_gateway(user),
        node_types=_node_catalog(session),
        schedules=ProjectSchedulerGateway(session, scheduler_client),
        cipher=PassphraseSecretsCipher(),
    ).execute(bundle, target, decisions, actor=_actor(user))
    return mappers.result_to_schema(result)
