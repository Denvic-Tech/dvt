from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

import config
from src.enums import ExtensionDepsStatus
from src.extensions.manifest import build_manifest_stub
from src.logger import logger
from src.models.extension import ExtensionRecord
from src.schemas.http.extension import ExtensionCreateSchema
from src.types import ExtensionManifest


class ExtensionDBManager:
    """Операции CRUD с расширениями в БД. Не работает с файловой системой."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_extensions(self) -> list[ExtensionRecord]:
        return (await self.session.execute(
            sa.select(ExtensionRecord).order_by(ExtensionRecord.name)
        )).scalars().all()

    async def get_extension(self, name: str) -> ExtensionRecord | None:
        return (await self.session.execute(
            sa.select(ExtensionRecord).where(ExtensionRecord.name == name)
        )).scalars().first()

    async def get_extension_or_raise(self, name: str) -> ExtensionRecord:
        extension = await self.get_extension(name)
        if extension is None:
            raise ValueError(f"Extension '{name}' not found.")
        return extension

    async def upsert_extension(
        self, data: ExtensionCreateSchema, manifest: ExtensionManifest | None = None
    ) -> ExtensionRecord:
        logger.debug(
            f"Upserting extension record name='{data.name}' repository_url='{data.repository_url}'"
        )

        now = datetime.now(UTC)
        upd_data = {}

        def _apply_update(target: ExtensionRecord, update_data: dict = None) -> None:
            if update_data is None:
                update_data = {}

            target.display_name = (
                data.display_name
                or (manifest.display_name if manifest else None)
                or target.display_name
                or data.name
            )
            target.description = (
                data.description
                if data.description is not None
                else (manifest.description if manifest else target.description)
            )
            target.repository_url = data.repository_url or target.repository_url
            target.manifest_json = self._build_manifest_json(
                name=target.name,
                display_name=target.display_name or target.name,
                description=target.description,
                repository_url=target.repository_url,
                existing_manifest=(
                    manifest.model_dump(mode="json") if manifest else target.manifest_json
                ),
            )
            target.last_version = manifest.version if manifest else target.last_version
            target.updated_at = now

        extension = await self.get_extension(data.name)

        if extension is None:
            extension = ExtensionRecord(
                name=data.name,
                display_name=(
                    data.display_name
                    or (manifest.display_name if manifest else None)
                    or data.name
                ),
                description=data.description or (manifest.description if manifest else "") or "",
                repository_url=data.repository_url,
                is_enabled=True,
                is_installed=False,
                deps_status=ExtensionDepsStatus.NOT_INSTALLED,
                manifest_json=self._build_manifest_json(
                    name=data.name,
                    display_name=(
                        data.display_name
                        or (manifest.display_name if manifest else None)
                        or data.name
                    ),
                    description=data.description or (manifest.description if manifest else "") or "",
                    repository_url=data.repository_url,
                    existing_manifest=manifest.model_dump(mode="json") if manifest else None,
                ),
                state_json={},
                created_at=now,
                updated_at=now,
                last_version=manifest.version if manifest else None,
            )
        else:
            _apply_update(extension, upd_data)

        merged_extension = await self.session.merge(extension)
        try:
            await self.session.commit()
            await self.session.refresh(merged_extension)
        except IntegrityError as exc:
            await self.session.rollback()
            if isinstance(getattr(exc, "orig", None), UniqueViolation):
                existing = await self.get_extension(data.name)
                if existing is None:
                    raise
                _apply_update(existing, upd_data)
                self.session.add(existing)
                await self.session.commit()
                await self.session.refresh(existing)
                merged_extension = existing
            else:
                raise

        logger.debug(
            f"Extension record upserted name='{merged_extension.name}' "
            f"installed={merged_extension.is_installed} "
            f"enabled={merged_extension.is_enabled}"
        )

        return merged_extension

    async def set_enabled(self, name: str, enabled: bool) -> ExtensionRecord:
        logger.debug(f"Setting extension '{name}' enabled={enabled}")
        extension = await self.get_extension_or_raise(name)
        extension.is_enabled = enabled
        extension.updated_at = datetime.now(UTC)
        self.session.add(extension)
        await self.session.commit()
        await self.session.refresh(extension)
        logger.debug(
            f"Extension '{extension.name}' enabled state updated to {extension.is_enabled}"
        )
        return extension

    async def delete_extension_record(self, extension: ExtensionRecord) -> None:
        logger.debug(f"Deleting extension record '{extension.name}'")
        await self.session.delete(extension)
        await self.session.commit()
        logger.debug(f"Extension record '{extension.name}' deleted")

    async def mark_installed(
        self,
        extension: ExtensionRecord,
        *,
        version: str,
        install_path: str,
        manifest: ExtensionManifest,
        display_name: str | None = None,
        description: str | None = None,
        latest_version: str | None = None,
    ) -> ExtensionRecord:
        logger.debug(f"Marking extension '{extension.name}' as installed version='{version}'")
        now = datetime.now(UTC)
        extension.display_name = display_name or manifest.display_name or extension.display_name or extension.name
        extension.description = description or manifest.description or extension.description
        extension.current_version = version
        extension.last_version = latest_version or version
        extension.install_path = install_path
        extension.manifest_json = manifest.model_dump(mode="json")
        extension.is_installed = True
        extension.deps_status = ExtensionDepsStatus.INSTALLING
        extension.error_message = None
        extension.installed_at = now
        extension.updated_at = now
        self.session.add(extension)
        await self.session.commit()
        await self.session.refresh(extension)
        return extension

    async def mark_uninstalled(self, extension: ExtensionRecord) -> ExtensionRecord:
        logger.debug(f"Marking extension '{extension.name}' as uninstalled")
        extension.is_installed = False
        extension.deps_status = ExtensionDepsStatus.NOT_INSTALLED
        extension.install_path = None
        extension.current_version = None
        extension.error_message = None
        extension.updated_at = datetime.now(UTC)
        self.session.add(extension)
        await self.session.commit()
        await self.session.refresh(extension)
        return extension

    async def mark_error(self, extension: ExtensionRecord, error_message: str) -> ExtensionRecord:
        logger.debug(f"Marking extension '{extension.name}' as error: {error_message}")
        extension.error_message = error_message
        extension.deps_status = ExtensionDepsStatus.ERROR
        extension.updated_at = datetime.now(UTC)
        self.session.add(extension)
        await self.session.commit()
        await self.session.refresh(extension)
        return extension

    async def set_runtime_error(
        self, extension: ExtensionRecord, error_message: str | None
    ) -> ExtensionRecord:
        """Persist a non-dependency extension error without corrupting deps_status."""
        extension.error_message = error_message
        extension.updated_at = datetime.now(UTC)
        self.session.add(extension)
        await self.session.commit()
        await self.session.refresh(extension)
        return extension

    async def sync_installed_extensions(
        self, discovered: dict[str, dict]
    ) -> list[ExtensionRecord]:
        """
        Синхронизирует найденные на диске расширения с БД.
        Принимает словарь {name: {root_dir, manifest}}, полученный от координатора.
        """
        logger.debug("Syncing installed extensions from discovered data")
        now = datetime.now(UTC)
        known = {
            item.name: item
            for item in (await self.session.execute(sa.select(ExtensionRecord))).scalars().all()
        }

        for ext_name, info in discovered.items():
            manifest = info["manifest"]
            root_dir = info["root_dir"]

            extension = known.get(ext_name)
            if extension is None:
                extension = self._find_known_extension_for_manifest(
                    known=known, manifest=manifest, root_dir=root_dir
                )
            if extension is None:
                extension = ExtensionRecord(
                    name=root_dir.name,
                    display_name=manifest.display_name or root_dir.name,
                    description=manifest.description,
                    repository_url=None,
                    is_enabled=True,
                    is_installed=True,
                    deps_status=ExtensionDepsStatus.NOT_INSTALLED,
                    current_version=manifest.version,
                    last_version=manifest.version,
                    install_path=str(root_dir),
                    manifest_json=manifest.model_dump(mode="json"),
                    state_json={},
                    installed_at=now,
                    created_at=now,
                    updated_at=now,
                )
            else:
                extension.display_name = manifest.display_name or extension.display_name
                extension.description = manifest.description or extension.description
                extension.is_installed = True
                extension.current_version = manifest.version
                extension.last_version = manifest.version
                extension.install_path = str(root_dir)
                extension.manifest_json = manifest.model_dump(mode="json")
                extension.updated_at = now

            self.session.add(extension)
            known[extension.name] = extension
            logger.debug(
                f"Synced extension '{extension.name}' version='{extension.current_version}' path='{extension.install_path}'"
            )

        # Помечаем как не установленные те, чьи пути исчезли
        for extension in known.values():
            install_path = extension.install_path
            if not install_path:
                continue
            if Path(install_path).exists():
                continue
            extension.is_installed = False
            extension.deps_status = ExtensionDepsStatus.NOT_INSTALLED
            extension.updated_at = now
            self.session.add(extension)
            logger.debug(
                f"Marked extension '{extension.name}' as not installed because path is missing: '{install_path}'"
            )

        await self.session.commit()
        logger.debug("Installed extensions sync completed")
        return await self.list_extensions()

    @staticmethod
    def _build_manifest_json(
        *,
        name: str,
        display_name: str,
        description: str,
        repository_url: str | None,
        existing_manifest: dict | None = None,
    ) -> dict:
        manifest_payload = dict(existing_manifest or {})
        return build_manifest_stub(
            name=name,
            version=manifest_payload.get("version", ""),
            display_name=display_name,
            description=description,
            repository_url=repository_url,
            homepage_url=manifest_payload.get("homepage_url"),
            dvt_version=manifest_payload.get("dvt_version"),
            backend=manifest_payload.get("backend"),
            frontend=manifest_payload.get("frontend"),
            requirements=manifest_payload.get("requirements"),
            state_schema=manifest_payload.get("state_schema"),
            nodes=manifest_payload.get("nodes"),
        )

    @staticmethod
    def _find_known_extension_for_manifest(
        *,
        known: dict[str, ExtensionRecord],
        manifest: ExtensionManifest,
        root_dir: Path,
    ) -> ExtensionRecord | None:
        root_dir_str = str(root_dir)
        for extension in known.values():
            if extension.install_path == root_dir_str:
                return extension
        return None
