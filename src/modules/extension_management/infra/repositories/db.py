from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from src.enums import ExtensionDepsStatus
from src.logger import logger
from src.modules.extension_management.domain.entities import ExtensionCreate
from src.modules.extension_management.domain.policies import (
    canonical_extension_name,
    extension_identity_set,
    normalize_extension_identity,
)
from src.modules.extension_management.domain.value_objects import ExtensionManifest
from src.modules.extension_management.infra.database import extension_schema_name
from src.modules.extension_management.infra.db_models import ExtensionRecord
from src.modules.extension_management.infra.identity import (
    manifest_with_aliases,
    resolve_record,
)
from src.modules.extension_management.infra.manifest import build_manifest_stub


class ExtensionDBManager:
    """Операции CRUD с расширениями в БД. Не работает с файловой системой."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_extensions(self) -> list[ExtensionRecord]:
        return (
            (await self.session.execute(sa.select(ExtensionRecord).order_by(ExtensionRecord.name)))
            .scalars()
            .all()
        )

    async def get_extension(self, name: str) -> ExtensionRecord | None:
        records = (await self.session.execute(sa.select(ExtensionRecord))).scalars().all()
        return resolve_record(records, name)

    async def get_extension_or_raise(self, name: str) -> ExtensionRecord:
        extension = await self.get_extension(name)
        if extension is None:
            raise ValueError(f"Extension '{name}' not found.")
        return extension

    async def upsert_extension(
        self, data: ExtensionCreate, manifest: ExtensionManifest | None = None
    ) -> ExtensionRecord:
        logger.debug(
            f"Upserting extension record name='{data.name}' repository_url='{data.repository_url}'"
        )

        canonical = canonical_extension_name(manifest.name if manifest else data.name)
        now = datetime.now(UTC)
        upd_data = {}

        def _apply_update(target: ExtensionRecord, update_data: dict | None = None) -> None:
            if update_data is None:
                update_data = {}

            declared = (target.manifest_json or {}).get("package_name")
            if declared and canonical_extension_name(declared) != canonical:
                raise ValueError(f"Conflicting package identity for extension '{target.name}'")
            old_name = target.name
            target.storage_schema = target.storage_schema or extension_schema_name(old_name)
            target.name = canonical
            target.manifest_json = manifest_with_aliases(
                target, {**(target.manifest_json or {}), "legacy_names": [old_name]}
            )
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
                    manifest_with_aliases(target, manifest.model_dump(mode="json"))
                    if manifest else target.manifest_json
                ),
            )
            target.last_version = manifest.version if manifest else target.last_version
            target.updated_at = now

        extension = await self.get_extension(canonical)

        if extension is None:
            extension = ExtensionRecord(
                name=canonical,
                storage_schema=extension_schema_name(canonical),
                display_name=(
                    data.display_name or (manifest.display_name if manifest else None) or data.name
                ),
                description=data.description or (manifest.description if manifest else "") or "",
                repository_url=data.repository_url,
                is_enabled=True,
                is_installed=False,
                deps_status=ExtensionDepsStatus.NOT_INSTALLED,
                manifest_json=self._build_manifest_json(
                    name=canonical,
                    display_name=(
                        data.display_name
                        or (manifest.display_name if manifest else None)
                        or data.name
                    ),
                    description=data.description
                    or (manifest.description if manifest else "")
                    or "",
                    repository_url=data.repository_url,
                    existing_manifest=manifest.model_dump(mode="json") if manifest else None,
                ),
                state_json={},
                created_at=now,
                updated_at=now,
                last_version=manifest.version if manifest else None,
            )
        else:
            if manifest is None:
                canonical = canonical_extension_name(
                    (extension.manifest_json or {}).get("package_name") or extension.name
                )
            _apply_update(extension, upd_data)

        merged_extension = await self.session.merge(extension)
        try:
            await self.session.commit()
            await self.session.refresh(merged_extension)
        except IntegrityError as exc:
            await self.session.rollback()
            if isinstance(getattr(exc, "orig", None), UniqueViolation):
                existing = await self.get_extension(canonical)
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

    async def reconcile_extension_identity(
        self,
        data: ExtensionCreate,
        manifest: ExtensionManifest | None = None,
        *,
        aliases: tuple[str, ...] = (),
        available_versions: list[str] | None = None,
    ) -> ExtensionRecord:
        """Atomically merge records that resolve to one canonical package identity."""
        canonical = canonical_extension_name(manifest.name if manifest else data.name)
        identities = extension_identity_set(
            data.name,
            manifest.package_name if manifest else None,
            aliases=(*aliases, *(manifest.legacy_names if manifest else ())),
        )
        # Serialize catalog/install reconciliation, including insertion of absent names.
        if self.session.get_bind().dialect.name == "postgresql":
            await self.session.execute(sa.text("LOCK TABLE extensions IN SHARE ROW EXCLUSIVE MODE"))
        records = (await self.session.execute(sa.select(ExtensionRecord))).scalars().all()
        candidates: list[ExtensionRecord] = []
        for item in records:
            payload = item.manifest_json or {}
            item_identities = extension_identity_set(
                item.name,
                payload.get("package_name"),
                aliases=(
                    alias for alias in payload.get("legacy_names", []) if isinstance(alias, str)
                ),
            )
            if identities.intersection(item_identities):
                candidates.append(item)
        if not candidates:
            created = await self.upsert_extension(
                ExtensionCreate(
                    name=canonical or data.name,
                    display_name=data.display_name,
                    description=data.description,
                    repository_url=data.repository_url,
                ),
                manifest,
            )
            if available_versions is not None:
                created.available_versions = list(available_versions)
                self.session.add(created)
                await self.session.commit()
                await self.session.refresh(created)
            return created

        def rank(item: ExtensionRecord) -> tuple[int, int, int, int]:
            return (
                int(bool(item.is_installed)),
                int(bool(item.install_path or item.state_json)),
                int(normalize_extension_identity(item.name) == canonical),
                int(bool(item.repository_url or item.available_versions)),
            )

        for item in candidates:
            declared = (item.manifest_json or {}).get("package_name")
            if declared and canonical_extension_name(declared) != canonical:
                raise ValueError(f"Conflicting package identity for extension '{item.name}'")
        owners = [
            item for item in candidates
            if item.is_installed or item.install_path or item.state_json or item.storage_schema
        ]
        if len(owners) > 1:
            raise ValueError(f"Multiple installations or states for extension '{canonical}'")
        survivor = max(candidates, key=rank)
        old_name = survivor.name
        survivor.storage_schema = survivor.storage_schema or extension_schema_name(old_name)
        catalog = max(
            candidates,
            key=lambda item: (
                int(bool(item.repository_url)),
                int(bool(item.available_versions)),
                int(bool(item.last_version)),
                int(normalize_extension_identity(item.name) == canonical),
            ),
        )
        survivor.display_name = (
            data.display_name
            or (manifest.display_name if manifest else None)
            or survivor.display_name
            or survivor.name
        )
        if data.description is not None:
            survivor.description = data.description
        elif manifest and manifest.description:
            survivor.description = manifest.description
        survivor.repository_url = (
            data.repository_url
            or survivor.repository_url
            or (catalog.repository_url if catalog is not None else None)
        )
        if available_versions is not None:
            survivor.available_versions = list(available_versions)
            survivor.last_version = (
                available_versions[0] if available_versions else survivor.last_version
            )
        elif catalog is not None and catalog is not survivor and catalog.available_versions:
            survivor.available_versions = list(catalog.available_versions)
            survivor.last_version = catalog.last_version or survivor.last_version

        if survivor.manifest_json:
            existing_manifest = dict(survivor.manifest_json)
            if manifest and manifest.package_name:
                existing_manifest["package_name"] = manifest.package_name
        else:
            existing_manifest = manifest.model_dump(mode="json") if manifest else None
        if existing_manifest:
            existing_manifest = dict(existing_manifest)
            existing_manifest["legacy_names"] = sorted(
                {
                    *existing_manifest.get("legacy_names", []),
                    *aliases,
                    *(manifest.legacy_names if manifest else ()),
                    *(item.name for item in candidates),
                }
            )
        survivor.manifest_json = self._build_manifest_json(
            name=canonical,
            display_name=survivor.display_name or survivor.name,
            description=survivor.description,
            repository_url=survivor.repository_url,
            existing_manifest=existing_manifest,
        )
        survivor.updated_at = datetime.now(UTC)
        self.session.add(survivor)
        for duplicate in candidates:
            if duplicate is survivor:
                continue
            if not survivor.is_installed and duplicate.is_installed:
                survivor.is_installed = duplicate.is_installed
                survivor.is_enabled = duplicate.is_enabled
                survivor.deps_status = duplicate.deps_status
                survivor.current_version = duplicate.current_version
                survivor.install_path = duplicate.install_path
                survivor.state_json = dict(duplicate.state_json or {})
                survivor.error_message = duplicate.error_message
                survivor.installed_at = duplicate.installed_at
            elif duplicate.state_json and not survivor.state_json:
                survivor.state_json = dict(duplicate.state_json)
            await self.session.delete(duplicate)
        # Delete a canonical catalog duplicate before renaming the surviving row.
        await self.session.flush()
        survivor.name = canonical
        await self.session.commit()
        await self.session.refresh(survivor)
        return survivor

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
        extension.display_name = (
            display_name or manifest.display_name or extension.display_name or extension.name
        )
        extension.description = description or manifest.description or extension.description
        extension.current_version = version
        extension.last_version = latest_version or version
        extension.install_path = install_path
        extension.manifest_json = manifest_with_aliases(extension, manifest.model_dump(mode="json"))
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

    async def sync_installed_extensions(self, discovered: dict[str, dict]) -> list[ExtensionRecord]:
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

            extension = self._find_known_extension_for_manifest(
                known=known, manifest=manifest, root_dir=root_dir
            )
            if extension is None:
                extension = known.get(ext_name)
            if extension is None:
                extension = ExtensionRecord(
                    name=canonical_extension_name(manifest.name),
                    storage_schema=extension_schema_name(manifest.name),
                    display_name=manifest.display_name or manifest.name,
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
                manifest_json = manifest_with_aliases(extension, manifest.model_dump(mode="json"))
                runtime_changed = any(
                    (
                        extension.display_name != (manifest.display_name or extension.display_name),
                        extension.description != (manifest.description or extension.description),
                        extension.is_installed is not True,
                        extension.current_version != manifest.version,
                        extension.last_version != manifest.version,
                        extension.install_path != str(root_dir),
                        extension.manifest_json != manifest_json,
                    )
                )
                extension.display_name = manifest.display_name or extension.display_name
                extension.description = manifest.description or extension.description
                extension.is_installed = True
                extension.current_version = manifest.version
                extension.last_version = manifest.version
                extension.install_path = str(root_dir)
                extension.manifest_json = manifest_json
                if runtime_changed:
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
            package_name=manifest_payload.get("package_name"),
            legacy_names=manifest_payload.get("legacy_names"),
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
                declared = (extension.manifest_json or {}).get("package_name")
                if declared and canonical_extension_name(declared) != manifest.name:
                    raise ValueError(f"Package identity changed at '{root_dir_str}'")
                return extension

        identities = extension_identity_set(
            manifest.name,
            manifest.package_name,
            aliases=manifest.legacy_names,
        )
        candidates: list[ExtensionRecord] = []
        for extension in known.values():
            payload = extension.manifest_json or {}
            extension_identities = extension_identity_set(
                extension.name,
                payload.get("package_name"),
                aliases=(
                    alias for alias in payload.get("legacy_names", []) if isinstance(alias, str)
                ),
            )
            if identities.intersection(extension_identities):
                candidates.append(extension)
        if not candidates:
            return None
        if len(candidates) > 1:
            raise ValueError(f"Ambiguous installed extension '{manifest.name}'")
        return candidates[0]
