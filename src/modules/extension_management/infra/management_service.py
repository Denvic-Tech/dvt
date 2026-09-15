import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.logger import logger
from src.modules.extension_management.domain.entities import ExtensionCreate
from src.modules.extension_management.domain.policies import (
    extension_identity_set,
    filter_compatible_versions,
    normalize_extension_identity,
    resolve_package_operation,
)
from src.modules.extension_management.domain.value_objects import (
    ExtensionManifest,
    ExtensionPackagePreview,
)
from src.modules.extension_management.infra.db_models import ExtensionRecord
from src.modules.extension_management.infra.errors import stage_error
from src.modules.extension_management.infra.migrations import ExtensionMigrationManager
from src.modules.extension_management.infra.packages.deletion_queue import (
    process_pending_deletions,
)
from src.modules.extension_management.infra.packages.installer import (
    ExtensionFrontendBundleInfo,
    ExtensionInstallSwap,
    ExtensionsInstallManager,
    load_manifest_from_repository,
)
from src.modules.extension_management.infra.repositories.db import ExtensionDBManager
from src.modules.extension_management.infra.runtime.gateway_runtime import (
    get_extension_gateway_runtime,
    prepare_extension_gateway_runtime,
)
from src.modules.extension_management.infra.runtime.loader import (
    check_dvt_compatibility,
    iter_extension_roots,
    load_manifest,
    load_manifest_payload,
)
from src.modules.extension_management.infra.runtime.runtime import (
    ExtensionLoadFailure,
    ExtensionRuntimeLoadError,
    ExtensionRuntimeSpec,
    load_all_extension_runtimes,
)

import config


class ExtensionManager:
    """
    Координатор управления расширениями.

    Объединяет ExtensionsInstallManager (файловая система) и
    ExtensionDBManager (база данных), сохраняя обратную совместимость API.
    """

    def __init__(self, session, distributor_client, *, gateway_runtime: bool = False):
        self.db_manager = ExtensionDBManager(session)
        self.install_manager = ExtensionsInstallManager()
        self.distributor_client = distributor_client
        self.gateway_runtime_enabled = gateway_runtime
        self.migration_manager = ExtensionMigrationManager()

    async def list_extensions(self) -> list[ExtensionRecord]:
        return await self.db_manager.list_extensions()

    async def get_extension(self, name: str) -> ExtensionRecord | None:
        return await self.db_manager.get_extension(name)

    async def get_extension_or_raise(self, name: str) -> ExtensionRecord:
        return await self.db_manager.get_extension_or_raise(name)

    async def set_enabled(self, name: str, enabled: bool) -> ExtensionRecord:
        previous = await self.get_extension_or_raise(name)
        previous_enabled = previous.is_enabled

        if enabled and self.gateway_runtime_enabled:
            if not previous.is_installed or not previous.install_path:
                raise ValueError(f"Extension '{name}' is not installed")
            if previous.error_message and not self._has_retryable_runtime_error(
                previous.error_message
            ):
                raise RuntimeError(
                    f"Extension '{name}' cannot be enabled while it has an unresolved error: "
                    f"{previous.error_message}"
                )
            try:
                manifest = load_manifest(Path(previous.install_path), extension_name=previous.name)
                if manifest is None:
                    raise ValueError(f"Manifest not found in '{previous.install_path}'")
                await asyncio.to_thread(self.migration_manager.upgrade, manifest)
                if self._has_retryable_runtime_error(previous.error_message):
                    await self.db_manager.set_runtime_error(previous, None)
            except Exception as exc:
                message = stage_error("Extension migration failed", exc)
                await self.db_manager.set_runtime_error(previous, message)
                await self._deactivate_extension_runtime(previous.name)
                raise RuntimeError(message) from exc

        runtime_name = previous.name
        extension = await self.db_manager.set_enabled(runtime_name, enabled)
        try:
            await self._refresh_runtime(
                strict_names=frozenset({runtime_name}) if enabled else frozenset()
            )
        except Exception:
            if previous_enabled != enabled:
                await self.db_manager.set_enabled(runtime_name, previous_enabled)
            raise
        return extension

    async def get_frontend_bundle_info(self, name: str) -> ExtensionFrontendBundleInfo:
        extension = await self.get_extension_or_raise(name)
        install_root, _ = self._load_frontend_config(extension)
        return ExtensionsInstallManager.get_frontend_bundle_info(
            install_root, extension.manifest_json or {}, extension.name
        )

    async def resolve_frontend_asset(self, name: str, asset_path: str) -> Path:
        extension = await self.get_extension_or_raise(name)
        install_root, _ = self._load_frontend_config(extension)
        return ExtensionsInstallManager.resolve_frontend_asset(
            install_root, extension.manifest_json or {}, extension.name, asset_path
        )

    async def upsert_extension(self, data: ExtensionCreate) -> ExtensionRecord:
        manifest = None
        if data.repository_url:
            manifest = await self._load_manifest_from_repository(data.repository_url)
        return await self.db_manager.upsert_extension(data, manifest)

    async def sync_available_extensions(self) -> list[ExtensionRecord]:
        logger.debug(
            "Syncing available extensions from distributor '{}'", config.EXTENSIONS.DISTRIBUTOR_URL
        )
        payload = await self.distributor_client.list_extensions(
            dvt_version=config.APP.VERSION or None, dvt_channel=config.APP.CHANNEL
        )

        extensions = payload.get("extensions") if isinstance(payload, dict) else None
        if not isinstance(extensions, list):
            logger.error(f"Extensions distributor returned unexpected payload: {payload}")
            return await self.list_extensions()

        synced: list[ExtensionRecord] = []
        for item in extensions:
            if not isinstance(item, dict):
                continue

            raw_name = item.get("name")
            if not isinstance(raw_name, str) or not raw_name.strip():
                continue
            canonical_name = normalize_extension_identity(raw_name)
            raw_versions = item.get("versions")
            version_strings = [
                value
                for value in (raw_versions if isinstance(raw_versions, list) else [])
                if isinstance(value, str)
            ]
            raw_aliases = item.get("legacy_aliases")
            aliases = tuple(
                value
                for value in (raw_aliases if isinstance(raw_aliases, list) else [])
                if isinstance(value, str) and value.strip()
            )
            manifest = ExtensionManifest(
                name=canonical_name,
                package_name=canonical_name,
                legacy_names=aliases,
                version=version_strings[0] if version_strings else "",
                display_name=item.get("display_name") or canonical_name,
                description=item.get("description") or "",
                repository_url=item.get("repository_url"),
            )
            extension = await self.db_manager.reconcile_extension_identity(
                ExtensionCreate(
                    name=canonical_name,
                    display_name=manifest.display_name,
                    description=manifest.description,
                    repository_url=manifest.repository_url,
                ),
                manifest,
                aliases=aliases,
                available_versions=version_strings,
            )
            synced.append(extension)

        return synced

    @staticmethod
    def _filter_compatible_versions(versions: list[dict] | None) -> list[dict]:
        return filter_compatible_versions(
            versions or [],
            current_dvt_version=config.APP.VERSION or None,
            channel=getattr(config.APP, "CHANNEL", "dev") or "dev",
        )

    async def install_extension(self, name: str, version: str | None = None) -> ExtensionRecord:
        extension = await self.get_extension_or_raise(name)
        distributor_name = self._distributor_extension_name(extension)

        versions_payload = await self.distributor_client.list_extension_versions(
            distributor_name,
            dvt_version=config.APP.VERSION or None,
            dvt_channel=config.APP.CHANNEL,
        )
        all_versions: list[dict] = (
            versions_payload.get("versions") if isinstance(versions_payload, dict) else []
        )
        if not all_versions:
            raise ValueError(f"No versions found for extension '{name}'")

        compatible = self._filter_compatible_versions(all_versions)
        if not compatible:
            raise ValueError(
                f"No compatible version of '{name}' found for DVT {config.APP.VERSION}"
            )

        if version:
            target = next((v for v in compatible if v.get("version") == version), None)
            if target is None:
                raise ValueError(
                    f"Version '{version}' of '{name}' is not compatible with DVT {config.APP.VERSION}"
                )
        else:
            target = compatible[0]

        download_url = target.get("download_url")
        if not download_url:
            raise ValueError(f"No download_url for '{name}' v{target.get('version')}")

        staged = await self.install_manager.stage_from_url(download_url)
        expected_identity = self._canonical_extension_identity(extension)
        if normalize_extension_identity(staged.manifest.name) != expected_identity:
            self.install_manager.rollback_staged_package(staged)
            raise ValueError(
                f"Downloaded package declares extension '{staged.manifest.name}', "
                f"expected '{expected_identity}'"
            )
        return await self._install_staged_package(
            extension,
            staged,
            latest_version=compatible[0].get("version"),
            offline_only=False,
        )

    async def preview_uploaded_package(
        self, fileobj, filename: str | None
    ) -> ExtensionPackagePreview:
        staged = await asyncio.to_thread(
            self.install_manager.stage_uploaded_package, fileobj, filename
        )
        manifest = staged.manifest
        existing = await self.get_extension(manifest.name)
        current_version = existing.current_version if existing and existing.is_installed else None
        operation = self._package_operation(current_version, manifest.version)
        compatible = check_dvt_compatibility(manifest)
        warnings: list[str] = []
        if not compatible:
            warnings.append(
                f"Расширение требует DVT {manifest.dvt_version}; текущая версия {config.APP.VERSION}."
            )
        if manifest.requirements and not staged.has_wheelhouse:
            warnings.append(
                "В пакете нет .dvt/wheels: установка зависимостей в air-gap режиме невозможна."
            )
        if operation == "downgrade":
            warnings.append("Будет выполнен downgrade установленного расширения.")
        elif operation == "reinstall":
            warnings.append("Будет выполнена повторная установка той же версии.")

        return ExtensionPackagePreview(
            package_id=staged.package_id,
            filename=filename or "extension.dvtx",
            name=manifest.name,
            display_name=manifest.display_name or manifest.name,
            version=manifest.version,
            current_version=current_version,
            dvt_version=manifest.dvt_version,
            operation=operation,
            compatible=compatible,
            offline_ready=compatible and (not manifest.requirements or staged.has_wheelhouse),
            has_wheelhouse=staged.has_wheelhouse,
            bundled_wheels_count=staged.bundled_wheels_count,
            warnings=tuple(warnings),
        )

    async def install_uploaded_package(
        self,
        package_id: str,
        *,
        allow_downgrade: bool = False,
        allow_reinstall: bool = False,
    ) -> ExtensionRecord:
        staged = self.install_manager.get_staged_package(package_id)
        manifest = staged.manifest
        if not check_dvt_compatibility(manifest):
            raise ValueError(
                f"Extension '{manifest.name}' v{manifest.version} requires DVT "
                f"{manifest.dvt_version}, but current DVT version is {config.APP.VERSION}"
            )
        if manifest.requirements and not staged.has_wheelhouse:
            raise ValueError(
                "Offline extension package has Python dependencies but no .dvt/wheels wheelhouse"
            )

        extension = await self._find_extension_for_manifest(manifest)
        current_version = (
            extension.current_version if extension and extension.is_installed else None
        )
        operation = self._package_operation(current_version, manifest.version)
        if operation == "downgrade" and not allow_downgrade:
            raise ValueError("Downgrade requires explicit confirmation")
        if operation == "reinstall" and not allow_reinstall:
            raise ValueError("Reinstall requires explicit confirmation")

        if extension is None:
            extension = await self.db_manager.reconcile_extension_identity(
                ExtensionCreate(
                    name=manifest.name,
                    display_name=manifest.display_name,
                    description=manifest.description,
                    repository_url=manifest.repository_url,
                ),
                manifest,
                aliases=manifest.legacy_names,
            )

        return await self._install_staged_package(
            extension,
            staged,
            latest_version=manifest.version,
            offline_only=True,
        )

    async def _install_staged_package(
        self,
        extension: ExtensionRecord,
        staged,
        *,
        latest_version: str | None,
        offline_only: bool,
    ) -> ExtensionRecord:
        install_root = (
            Path(extension.install_path)
            if extension.is_installed and extension.install_path
            else Path(config.EXTENSIONS.EXTENSIONS_DATA_DIR) / staged.manifest.name
        )
        previous = self._snapshot_install_record(extension)
        swap: ExtensionInstallSwap | None = None
        try:
            swap = self.install_manager.activate_staged_package(staged, install_root)
            manifest = load_manifest(install_root, extension_name=extension.name)
            if manifest is None:
                raise ValueError(f"Manifest not found in '{install_root}'")
            if not check_dvt_compatibility(manifest):
                raise ValueError(
                    f"Extension '{manifest.name}' v{manifest.version} requires DVT "
                    f"{manifest.dvt_version}, but current DVT version is {config.APP.VERSION}"
                )

            extension = await self.db_manager.mark_installed(
                extension,
                version=manifest.version,
                install_path=str(install_root),
                manifest=manifest,
                display_name=manifest.display_name,
                description=manifest.description,
                latest_version=latest_version,
            )
            await self.install_manager.install_requirements(install_root, offline_only=offline_only)
            await asyncio.to_thread(self.migration_manager.upgrade, manifest)
            await self._refresh_runtime(strict_names=frozenset({extension.name}))
            self.install_manager._broadcast_extension_deps_install(extension.name)
            self.install_manager.commit_install_swap(swap)
            logger.debug(
                "Extension '{}' installed successfully with version='{}'",
                extension.name,
                extension.current_version,
            )
            result = extension
        except Exception as exc:
            logger.exception("Extension '{}' installation failed", extension.name)
            if swap is not None:
                try:
                    self.install_manager.rollback_install_swap(swap)
                except Exception:
                    logger.exception("Failed to roll back extension files for '{}'", extension.name)
            else:
                try:
                    self.install_manager.rollback_staged_package(staged)
                except Exception:
                    logger.exception("Failed to discard staged package for '{}'", extension.name)
            try:
                extension = await self._restore_install_record(extension, previous)
                if previous["is_installed"] and previous["install_path"]:
                    await self._refresh_runtime(strict_names=frozenset({extension.name}))
                else:
                    await self._deactivate_extension_runtime(extension.name)
            except Exception:
                logger.exception("Failed to restore install state for '{}'", extension.name)
                await self._deactivate_extension_runtime(extension.name)
            raise RuntimeError(stage_error("Extension install failed", exc)) from exc
        else:
            return result

    @staticmethod
    def _package_operation(current_version: str | None, package_version: str) -> str:
        return resolve_package_operation(current_version, package_version).value

    @staticmethod
    def _snapshot_install_record(extension: ExtensionRecord) -> dict[str, Any]:
        fields = (
            "display_name",
            "description",
            "is_enabled",
            "is_installed",
            "deps_status",
            "current_version",
            "last_version",
            "install_path",
            "manifest_json",
            "error_message",
            "installed_at",
            "updated_at",
        )
        return {field: getattr(extension, field) for field in fields}

    async def _restore_install_record(
        self, extension: ExtensionRecord, snapshot: dict[str, Any]
    ) -> ExtensionRecord:
        for field, value in snapshot.items():
            setattr(extension, field, value)
        session = self.db_manager.session
        session.add(extension)
        await session.commit()
        await session.refresh(extension)
        return extension

    async def delete_extension(self, name: str) -> None:
        logger.debug(f"Deleting extension '{name}'")
        extension = await self.get_extension_or_raise(name)

        install_path = extension.install_path
        if install_path:
            self.install_manager.uninstall(Path(install_path))

        await self.db_manager.delete_extension_record(extension)
        await self._refresh_runtime()
        logger.debug(f"Extension '{name}' deleted")

    async def uninstall_extension(
        self, name: str, *, drop_extension_data: bool = False
    ) -> ExtensionRecord:
        logger.debug(f"Uninstalling extension '{name}'")
        extension = await self.get_extension_or_raise(name)

        if drop_extension_data:
            try:
                await asyncio.to_thread(self.migration_manager.drop_schema, extension.name)
            except Exception as exc:
                await self.db_manager.set_runtime_error(
                    extension, stage_error("Extension data removal failed", exc)
                )
                raise RuntimeError(stage_error("Extension data removal failed", exc)) from exc

        records = await self.list_extensions()
        await self._refresh_runtime(records=[item for item in records if item.id != extension.id])

        install_path = extension.install_path
        if install_path:
            self.install_manager.uninstall(Path(install_path))

        extension = await self.db_manager.mark_uninstalled(extension)
        await self._refresh_runtime()
        logger.debug(f"Extension '{name}' uninstalled")
        return extension

    async def reload_extension(self, name: str) -> ExtensionRecord:
        logger.debug(f"Reloading (upgrading) extension '{name}'")

        extension = await self.get_extension_or_raise(name)
        distributor_name = self._distributor_extension_name(extension)

        versions_payload = await self.distributor_client.list_extension_versions(
            distributor_name,
            dvt_version=config.APP.VERSION or None,
            dvt_channel=config.APP.CHANNEL,
        )
        all_versions: list[dict] = (
            versions_payload.get("versions") if isinstance(versions_payload, dict) else []
        )
        compatible = self._filter_compatible_versions(all_versions)
        if not compatible:
            raise ValueError(
                f"No compatible version of '{name}' found for DVT {config.APP.VERSION}"
            )

        latest = compatible[0]
        remote_version = latest.get("version")
        if not remote_version:
            raise RuntimeError("Failed to determine latest version from distributor")

        current_version = extension.current_version

        if current_version == remote_version:
            logger.debug(f"No new version for '{name}', reloading runtime only")

            if not extension.install_path:
                raise ValueError(f"Extension '{name}' has no install path")
            install_root = Path(extension.install_path)
            manifest = load_manifest(install_root, extension_name=extension.name)

            if manifest is None:
                raise ValueError(f"Manifest not found in '{install_root}'")

            try:
                await asyncio.to_thread(self.migration_manager.upgrade, manifest)
            except Exception as exc:
                await self.db_manager.set_runtime_error(
                    extension, stage_error("Extension migration failed", exc)
                )
                await self._deactivate_extension_runtime(extension.name)
                raise RuntimeError(stage_error("Extension migration failed", exc)) from exc

            await self._refresh_runtime(strict_names=frozenset({extension.name}))

            extension.manifest_json = manifest.model_dump(mode="json")
            extension.updated_at = datetime.now(UTC)

            session = self.db_manager.session
            session.add(extension)
            await session.commit()
            await session.refresh(extension)

            return extension

        logger.debug(f"Updating extension '{name}' from {current_version} -> {remote_version}")

        return await self.install_extension(name)

    async def sync_installed_extensions(self) -> list[ExtensionRecord]:
        logger.debug(f"Syncing installed extensions from '{config.EXTENSIONS.EXTENSIONS_DATA_DIR}'")
        process_pending_deletions(self.install_manager._remove_install_root)

        discovered: dict[str, dict] = {}
        manifest_failures: dict[str, Exception] = {}
        for root_dir in iter_extension_roots():
            try:
                manifest = load_manifest_payload(root_dir)
                if manifest is None:
                    raise ValueError(f"Manifest not found in '{root_dir}'")
                discovered[manifest.name] = {"root_dir": root_dir, "manifest": manifest}
            except Exception as exc:
                manifest_failures[root_dir.name] = exc
                logger.exception("Failed to parse extension manifest from '{}'", root_dir)

        result = await self.db_manager.sync_installed_extensions(discovered)
        for info in discovered.values():
            manifest = info["manifest"]
            await self.db_manager.reconcile_extension_identity(
                ExtensionCreate(
                    name=manifest.name,
                    display_name=manifest.display_name,
                    description=manifest.description,
                    repository_url=manifest.repository_url,
                ),
                manifest,
                aliases=manifest.legacy_names,
            )
        result = await self.list_extensions()

        records_by_name = {item.name: item for item in result}
        for extension_name, exc in manifest_failures.items():
            record = records_by_name.get(extension_name)
            if record is not None:
                await self.db_manager.set_runtime_error(
                    record, stage_error("Manifest validation failed", exc)
                )

        if self.gateway_runtime_enabled:
            for extension in result:
                if not extension.is_installed or not extension.install_path:
                    continue
                if extension.name in manifest_failures:
                    continue
                try:
                    manifest = load_manifest(
                        Path(extension.install_path), extension_name=extension.name
                    )
                    if manifest is None:
                        raise ValueError(f"Manifest not found in '{extension.install_path}'")
                    await asyncio.to_thread(self.migration_manager.upgrade, manifest)
                    if self._has_retryable_runtime_error(extension.error_message):
                        await self.db_manager.set_runtime_error(extension, None)
                except Exception as exc:
                    await self.db_manager.set_runtime_error(
                        extension, stage_error("Extension migration failed", exc)
                    )
        await self._refresh_runtime(records=result)
        return await self.list_extensions()

    async def _deactivate_extension_runtime(self, name: str) -> None:
        """Best-effort removal of an extension whose installed files are not healthy.

        Install/update is intentionally not a blue/green package swap. Once an
        install attempt has started mutating the extension directory, an older
        in-memory generation must therefore not remain callable after a failure.
        Gateway routes can be removed immediately; node registries are rebuilt
        from all remaining healthy extension records.
        """
        if self.gateway_runtime_enabled:
            get_extension_gateway_runtime().remove(name)

        try:
            records = await self.list_extensions()
            await self._refresh_runtime(records=[item for item in records if item.name != name])
        except Exception:
            logger.exception("Failed to fully deactivate unhealthy extension runtime '{}'", name)

    async def _refresh_runtime(
        self,
        *,
        records: list[ExtensionRecord] | None = None,
        strict_names: frozenset[str] = frozenset(),
    ):
        records = records if records is not None else await self.list_extensions()
        specs = [
            ExtensionRuntimeSpec(name=item.name, root_dir=Path(item.install_path))
            for item in records
            if item.is_installed
            and item.is_enabled
            and item.install_path
            and (
                not getattr(item, "error_message", None)
                or self._has_retryable_node_runtime_error(
                    getattr(item, "error_message", None)
                )
                or (
                    item.name in strict_names
                    and self._has_retryable_runtime_error(getattr(item, "error_message", None))
                )
            )
        ]
        gateway_failures: dict[str, ExtensionLoadFailure] = {}
        gateway_apps = {}
        node_specs = specs

        if self.gateway_runtime_enabled:
            gateway_report = prepare_extension_gateway_runtime(specs)
            gateway_failures = gateway_report.failures
            node_specs = [spec for spec in specs if spec.name not in gateway_failures]
            gateway_apps = gateway_report.apps

        report = load_all_extension_runtimes(
            node_specs,
            preloaded_extension_names=frozenset(gateway_apps),
        )
        for name, failure in gateway_failures.items():
            report.failures[name] = failure

        if self.gateway_runtime_enabled:
            healthy_names = set(report.loaded)
            get_extension_gateway_runtime().swap(
                {name: app for name, app in gateway_apps.items() if name in healthy_names}
            )

        records_by_name = {item.name: item for item in records}
        for failure in report.failures.values():
            logger.error(
                "Extension '{}' excluded from runtime at stage '{}': {}",
                failure.extension_name,
                failure.stage,
                failure.message,
            )
            record = records_by_name.get(failure.extension_name)
            if record is not None:
                await self.db_manager.set_runtime_error(
                    record, self._format_runtime_failure(failure)
                )

        for loaded_name in report.loaded:
            record = records_by_name.get(loaded_name)
            if record is not None and self._has_retryable_runtime_error(
                getattr(record, "error_message", None)
            ):
                await self.db_manager.set_runtime_error(record, None)

        strict_failures = sorted(strict_names.intersection(report.failures))
        if strict_failures:
            raise ExtensionRuntimeLoadError(report.failures[strict_failures[0]])
        return report

    @staticmethod
    def _has_retryable_runtime_error(error_message: str | None) -> bool:
        if not error_message:
            return False
        return error_message.startswith(
            (
                "Manifest validation failed:",
                "Extension migration failed:",
                "Gateway entrypoint import failed:",
                "Extension router validation failed:",
                "Extension node backend validation failed:",
                "Extension node import failed:",
                "Extension node registry failed:",
                "Extension runtime failed:",
            )
        )

    @staticmethod
    def _has_retryable_node_runtime_error(error_message: str | None) -> bool:
        if not error_message:
            return False
        return error_message.startswith(
            (
                "Extension node backend validation failed:",
                "Extension node import failed:",
                "Extension node registry failed:",
                "Extension runtime failed:",
            )
        )

    @staticmethod
    def _format_runtime_failure(failure: ExtensionLoadFailure) -> str:
        stage_names = {
            "manifest": "Manifest validation failed",
            "backend_package": "Extension node backend validation failed",
            "import": "Extension node import failed",
            "node_registry": "Extension node registry failed",
            "registry": "Extension node registry failed",
            "gateway_import": "Gateway entrypoint import failed",
            "gateway_validation": "Extension router validation failed",
        }
        return stage_error(
            stage_names.get(failure.stage, "Extension runtime failed"), failure.message
        )

    async def _find_extension_for_manifest(
        self, manifest: ExtensionManifest
    ) -> ExtensionRecord | None:
        identities = extension_identity_set(
            manifest.name,
            manifest.package_name,
            aliases=manifest.legacy_names,
        )
        for extension in await self.list_extensions():
            manifest_json = extension.manifest_json or {}
            extension_identities = extension_identity_set(
                extension.name,
                manifest_json.get("package_name"),
                aliases=(
                    alias
                    for alias in manifest_json.get("legacy_names", [])
                    if isinstance(alias, str)
                ),
            )
            if identities.intersection(extension_identities):
                return extension
        return None

    @staticmethod
    def _canonical_extension_identity(extension: ExtensionRecord) -> str:
        manifest_json = extension.manifest_json or {}
        return normalize_extension_identity(
            manifest_json.get("package_name") or manifest_json.get("name") or extension.name
        )

    @classmethod
    def _distributor_extension_name(cls, extension: ExtensionRecord) -> str:
        """Return the canonical package identity expected by the distributor."""
        return cls._canonical_extension_identity(extension) or extension.name

    async def _load_manifest_from_repository(self, repository_url: str) -> ExtensionManifest | None:
        return await load_manifest_from_repository(repository_url)

    @staticmethod
    def _build_manifest_json(
        *,
        name: str,
        display_name: str,
        description: str,
        repository_url: str | None,
        existing_manifest: dict | None = None,
    ) -> dict:
        return ExtensionDBManager._build_manifest_json(
            name=name,
            display_name=display_name,
            description=description,
            repository_url=repository_url,
            existing_manifest=existing_manifest,
        )

    @staticmethod
    def _find_known_extension_for_manifest(
        *,
        known: dict[str, ExtensionRecord],
        manifest: ExtensionManifest,
        root_dir: Path,
    ) -> ExtensionRecord | None:
        return ExtensionDBManager._find_known_extension_for_manifest(
            known=known, manifest=manifest, root_dir=root_dir
        )

    def _remove_install_root(self, install_root: Path) -> None:
        self.install_manager._remove_install_root(install_root)

    def _load_frontend_config(self, extension: ExtensionRecord) -> tuple[Path, dict[str, Any]]:
        if not extension.is_installed or not extension.install_path:
            raise ValueError(f"Расширение '{extension.name}' не установлено.")
        frontend = (extension.manifest_json or {}).get("frontend") or {}
        if not frontend:
            raise FileNotFoundError(f"Расширение '{extension.name}' не имеет фронтенд-бандла.")
        install_root = Path(extension.install_path).resolve()
        return install_root, frontend
