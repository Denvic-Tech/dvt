from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.params import Query
from fastapi.responses import FileResponse

from services.gateway.deps.extensions import get_extension_manager

from src.modules.extension_management.domain.entities import Extension
from src.modules.extension_management.flow.providers import ExtensionManagementProvider
from src.modules.extension_management.infra.state_manager import ExtensionStateManager
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly, UserSuperadminAccessOnly
from src.schemas.http.common import CommonResponse
from src.schemas.http.extension import (
    ExtensionFrontendReadSchema,
    ExtensionPackagePreviewSchema,
    ExtensionReadSchema,
    ExtensionStateReadSchema,
    ExtensionStateUpdateSchema,
    ExtensionUninstallSchema,
)

r = router = APIRouter(prefix="/extensions", tags=["Extensions"])

ExtensionManagerDep = Annotated[ExtensionManagementProvider, Depends(get_extension_manager)]


def _to_extension_read(item: Extension) -> ExtensionReadSchema:
    """Конвертирует domain extension в нормализованную схему ответа API."""
    return ExtensionReadSchema(
        id=item.id,
        name=item.name,
        display_name=item.display_name,
        description=item.description,
        repository_url=item.repository_url,
        is_enabled=item.is_enabled,
        is_installed=item.is_installed,
        deps_status=item.deps_status.value,
        current_version=item.current_version,
        last_version=item.last_version,
        install_path=item.install_path,
        manifest_json=item.manifest_json or {},
        state_json=item.state_json or {},
        available_versions=item.available_versions,
        error_message=item.error_message,
        installed_at=item.installed_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.post("/sync", response_model=list[ExtensionReadSchema])
async def sync_extensions(
    user: UserSuperadminAccessOnly,  # noqa: ARG001
    extension_manager: ExtensionManagerDep,
) -> list[ExtensionReadSchema]:
    """Синхронизирует доступные расширения из дистрибьютора с состоянием БД."""
    items = await extension_manager.sync_available_extensions()
    return [_to_extension_read(item=item) for item in items]


@router.get("", response_model=list[ExtensionReadSchema])
async def list_extensions(
    user: UserSuperadminAccessOnly,  # noqa: ARG001
    extension_manager: ExtensionManagerDep,
) -> list[ExtensionReadSchema]:
    """Возвращает все записи о расширениях, известные системе."""
    items = await extension_manager.list_extensions()
    return [_to_extension_read(item=item) for item in items]


@router.post("/packages/preview", response_model=ExtensionPackagePreviewSchema)
async def preview_extension_package(
    user: UserSuperadminAccessOnly,  # noqa: ARG001
    extension_manager: ExtensionManagerDep,
    file: Annotated[UploadFile, File(...)],
) -> ExtensionPackagePreviewSchema:
    """Загружает и валидирует локальный .dvtx/.zip без изменения runtime."""
    try:
        return await extension_manager.preview_uploaded_package(file.file, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/packages/{package_id}/install", response_model=ExtensionReadSchema)
async def install_extension_package(
    package_id: str,
    user: UserSuperadminAccessOnly,  # noqa: ARG001
    extension_manager: ExtensionManagerDep,
    allow_downgrade: Annotated[bool, Query()] = False,
    allow_reinstall: Annotated[bool, Query()] = False,
) -> ExtensionReadSchema:
    """Устанавливает ранее загруженный package полностью из локального artifact."""
    try:
        extension = await extension_manager.install_uploaded_package(
            package_id,
            allow_downgrade=allow_downgrade,
            allow_reinstall=allow_reinstall,
        )
        return _to_extension_read(item=extension)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{extension_name}/frontend", response_model=ExtensionFrontendReadSchema)
async def get_extension_frontend(
    extension_name: str,
    request: Request,
    extension_manager: ExtensionManagerDep,
) -> ExtensionFrontendReadSchema:
    """Возвращает метаданные фронтенд бандла для запрошенного установленного расширения."""
    try:
        bundle_info = await extension_manager.get_frontend_bundle_info(extension_name)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Берём root_path, чтобы учесть router_prefix
    root_path = request.scope.get("root_path", "")

    return ExtensionFrontendReadSchema(
        extension_name=extension_name,
        installed=True,
        bundle_url=f"{root_path}/extensions/{extension_name}/frontend/assets/{bundle_info.bundle_path.name}",
        entry_file=bundle_info.entry_file,
        entrypoint=bundle_info.entrypoint,
    )


@router.get("/{extension_name}/frontend/assets/{asset_path:path}")
async def get_extension_frontend_asset(
    extension_name: str,
    asset_path: str,
    extension_manager: ExtensionManagerDep,
) -> FileResponse:
    """Отдает файл фронтенд ассета из директории dist установленного расширения."""
    try:
        target_path = await extension_manager.resolve_frontend_asset(extension_name, asset_path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return FileResponse(
        target_path,
        media_type="application/javascript",  # или 'text/javascript'
    )


@router.delete("/{extension_name}/uninstall", response_model=ExtensionReadSchema)
async def uninstall_extension(
    extension_name: str,
    user: UserSuperadminAccessOnly,  # noqa: ARG001
    extension_manager: ExtensionManagerDep,
    data: ExtensionUninstallSchema | None = None,
) -> ExtensionReadSchema:
    """Удаляет файлы установленного расширения, сохраняя запись в БД."""
    uninstall_data = data or ExtensionUninstallSchema()
    try:
        extension = await extension_manager.uninstall_extension(
            extension_name, drop_extension_data=uninstall_data.drop_extension_data
        )
        return _to_extension_read(item=extension)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{extension_name}/install", response_model=ExtensionReadSchema)
async def install_extension(
    extension_name: str,
    user: UserSuperadminAccessOnly,  # noqa: ARG001
    extension_manager: ExtensionManagerDep,
    version: Annotated[str | None, Query()] = None,
) -> ExtensionReadSchema:
    """Устанавливает файлы расширения, зависимости и обновляет состояние БД."""
    try:
        extension = await extension_manager.install_extension(extension_name, version=version)
        return _to_extension_read(item=extension)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{extension_name}/reload", response_model=ExtensionReadSchema)
async def reload_extension(
    extension_name: str,
    user: UserSuperadminAccessOnly,  # noqa: ARG001
    extension_manager: ExtensionManagerDep,
) -> ExtensionReadSchema:
    """Перезагружает уже установленное расширение с диска в рантайм и БД."""
    try:
        extension = await extension_manager.reload_extension(extension_name)
        return _to_extension_read(item=extension)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{extension_name}/enable", response_model=ExtensionReadSchema)
async def enable_extension(
    extension_name: str,
    user: UserSuperadminAccessOnly,  # noqa: ARG001
    extension_manager: ExtensionManagerDep,
) -> ExtensionReadSchema:
    """Включает расширение, делая его установленные узлы доступными в системе."""
    try:
        extension = await extension_manager.set_enabled(extension_name, enabled=True)
        return _to_extension_read(item=extension)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{extension_name}/disable", response_model=ExtensionReadSchema)
async def disable_extension(
    extension_name: str,
    user: UserSuperadminAccessOnly,  # noqa: ARG001
    extension_manager: ExtensionManagerDep,
) -> ExtensionReadSchema:
    """Отключает расширение без удаления его записи или установленных файлов."""
    try:
        extension = await extension_manager.set_enabled(extension_name, enabled=False)
        return _to_extension_read(item=extension)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{extension_name}/state", response_model=ExtensionStateReadSchema)
async def get_extension_state(
    user: UserAccessOnly,  # noqa: ARG001
    extension_name: str,
    key: Annotated[str, Query()] = "default",
) -> ExtensionStateReadSchema:
    """Возвращает сохраненное состояние расширения для запрошенного логического ключа."""
    return ExtensionStateReadSchema(
        extension_name=extension_name,
        state_key=key,
        value=await ExtensionStateManager.async_get_state(extension_name, key=key),
    )


@router.put("/{extension_name}/state", response_model=ExtensionStateReadSchema)
async def update_extension_state(
    user: UserAccessOnly,  # noqa: ARG001
    extension_name: str,
    data: ExtensionStateUpdateSchema,
    key: Annotated[str, Query()] = "default",
) -> ExtensionStateReadSchema:
    """Сохраняет состояние расширения для запрошенного логического ключа."""
    return ExtensionStateReadSchema(
        extension_name=extension_name,
        state_key=key,
        value=await ExtensionStateManager.async_set_state(
            extension_name, key=key, value=data.value
        ),
    )


@router.post("/reload-installed", response_model=CommonResponse)
async def reload_installed_extensions(
    user: UserSuperadminAccessOnly,  # noqa: ARG001
    extension_manager: ExtensionManagerDep,
) -> CommonResponse:
    """Принудительно перезагружает в рантайм и синхронизирует с БД все установленные расширения."""
    await extension_manager.sync_installed_extensions()
    return CommonResponse(success=True, message="Установленные расширения перезагружены.")
