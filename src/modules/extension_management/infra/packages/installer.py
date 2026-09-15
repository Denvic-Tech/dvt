from __future__ import annotations

import asyncio
import shutil
import stat
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from src.logger import logger
from src.modules.extension_management.domain.value_objects import ExtensionManifest
from src.modules.extension_management.infra.dependency_manager import get_dependency_manager
from src.modules.extension_management.infra.packages.artifact import (
    StagedExtensionPackage,
    discard_staged_extension_package,
    get_staged_extension_package,
    stage_extension_package,
)
from src.modules.extension_management.infra.packages.deletion_queue import add_pending_deletion
from src.modules.extension_management.infra.packages.dependencies import (
    build_extension_pip_install_command,
)
from src.modules.extension_management.infra.runtime.loader import load_manifest

import config


@dataclass
class ExtensionFrontendBundleInfo:
    bundle_path: Path
    assets_root: Path
    entry_file: str
    entrypoint: str | None


@dataclass(frozen=True)
class ExtensionInstallSwap:
    install_root: Path
    backup_root: Path | None
    stage_dir: Path


async def load_manifest_from_repository(repository_url: str) -> ExtensionManifest | None:
    """Загружает manifest расширения из distributable archive по URL."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(repository_url)
            resp.raise_for_status()

        with tempfile.TemporaryDirectory(prefix="dvt-extension-manifest-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            archive_name = Path(urlsplit(repository_url).path).name or "extension.zip"
            suffix = Path(archive_name).suffix.lower()
            if suffix not in {".zip", ".dvtx"}:
                archive_name = f"{archive_name}.zip"
            archive_path = tmp_path / archive_name
            archive_path.write_bytes(resp.content)
            with archive_path.open("rb") as fileobj:
                staged = stage_extension_package(fileobj, archive_name)
            try:
                return staged.manifest
            finally:
                discard_staged_extension_package(staged.package_id)
    except Exception:
        logger.exception(
            "Failed to load manifest from archive '{}'; keeping local stub manifest",
            repository_url,
        )
        return None


class ExtensionsInstallManager:
    """Управление установкой расширений на файловой системе (без БД)."""

    def _broadcast_extension_deps_install(self, extension_name: str) -> None:
        dependency_manager = get_dependency_manager()
        sent_count = dependency_manager.broadcast_install_task(extension_name)
        logger.debug(f"Extension deps install broadcasted to {sent_count} workers")

    def stage_uploaded_package(
        self, fileobj: BinaryIO, filename: str | None
    ) -> StagedExtensionPackage:
        return stage_extension_package(fileobj, filename)

    def get_staged_package(self, package_id: str) -> StagedExtensionPackage:
        return get_staged_extension_package(package_id)

    @staticmethod
    def rollback_staged_package(staged: StagedExtensionPackage) -> None:
        discard_staged_extension_package(staged.package_id)

    async def stage_from_url(self, repository_url: str) -> StagedExtensionPackage:
        logger.debug("Downloading extension package from '{}'", repository_url)
        archive_name = Path(urlsplit(repository_url).path).name or "extension.zip"
        if Path(archive_name).suffix.lower() not in {".zip", ".dvtx"}:
            archive_name = f"{archive_name}.zip"

        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(archive_name).suffix) as tmp:
            tmp_path = Path(tmp.name)
        downloaded = 0
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0)
            ) as client, client.stream("GET", repository_url) as resp:
                resp.raise_for_status()
                content_length = resp.headers.get("Content-Length")
                if (
                    content_length
                    and int(content_length) > config.EXTENSIONS.PACKAGE_MAX_SIZE_BYTES
                ):
                    raise ValueError("Extension package is too large")
                with tmp_path.open("wb") as output:
                    async for chunk in resp.aiter_bytes():
                        downloaded += len(chunk)
                        if downloaded > config.EXTENSIONS.PACKAGE_MAX_SIZE_BYTES:
                            raise ValueError("Extension package is too large")
                        output.write(chunk)

            with tmp_path.open("rb") as fileobj:
                return await asyncio.to_thread(
                    stage_extension_package, fileobj, archive_name
                )
        finally:
            tmp_path.unlink(missing_ok=True)

    async def install_from_url(self, repository_url: str, install_root: Path) -> None:
        staged = await self.stage_from_url(repository_url)
        swap: ExtensionInstallSwap | None = None
        try:
            swap = self.activate_staged_package(staged, install_root)
            self.commit_install_swap(swap)
        except Exception:
            if swap is not None:
                self.rollback_install_swap(swap)
            else:
                discard_staged_extension_package(staged.package_id)
            raise

    async def install_requirements(
        self, install_root: Path, *, offline_only: bool = False
    ) -> None:
        pyproject_path = install_root / "pyproject.toml"
        if not pyproject_path.exists():
            logger.debug(f"No pyproject.toml found for extension in '{install_root}'")
            return

        try:
            payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            logger.error("Invalid pyproject.toml for extension in '{}': {}", install_root, exc)
            raise ValueError("Invalid pyproject.toml for extension") from exc

        project = payload.get("project") or {}
        dependencies = project.get("dependencies") or []
        if not isinstance(dependencies, list):
            logger.error(
                "Invalid [project].dependencies in '{}': expected list, got {}",
                pyproject_path,
                type(dependencies).__name__,
            )
            raise TypeError("Invalid [project].dependencies in pyproject.toml")

        requirements = [item for item in dependencies if isinstance(item, str) and item.strip()]
        if not requirements:
            logger.debug(f"No [project].dependencies found for extension in '{install_root}'")
            return

        logger.debug(
            "Installing extension dependencies from '{}' into the current Python environment",
            pyproject_path,
        )
        command = build_extension_pip_install_command(
            requirements,
            install_root=install_root,
            offline_only=offline_only,
        )
        await self._run_command(command)
        logger.debug("Successfully installed extension dependencies")

    def activate_staged_package(
        self, staged: StagedExtensionPackage, install_root: Path
    ) -> ExtensionInstallSwap:
        install_root = install_root.resolve()
        install_root.parent.mkdir(parents=True, exist_ok=True)
        token = uuid4().hex
        candidate_root = install_root.parent / f".{install_root.name}.candidate-{token}"
        backup_root = (
            install_root.parent / f".{install_root.name}.backup-{token}"
            if install_root.exists()
            else None
        )

        try:
            shutil.move(str(staged.root_dir), str(candidate_root))
            if backup_root is not None:
                install_root.replace(backup_root)
            candidate_root.replace(install_root)
        except Exception:
            if install_root.exists() and backup_root is not None and backup_root.exists():
                self._remove_install_root(install_root)
            if backup_root is not None and backup_root.exists() and not install_root.exists():
                backup_root.replace(install_root)
            if candidate_root.exists():
                self._remove_install_root(candidate_root)
            discard_staged_extension_package(staged.package_id)
            raise

        return ExtensionInstallSwap(
            install_root=install_root,
            backup_root=backup_root,
            stage_dir=staged.stage_dir,
        )

    def commit_install_swap(self, swap: ExtensionInstallSwap) -> None:
        if swap.backup_root is not None and swap.backup_root.exists():
            self._remove_install_root(swap.backup_root)
        shutil.rmtree(swap.stage_dir, ignore_errors=True)

    def rollback_install_swap(self, swap: ExtensionInstallSwap) -> None:
        if swap.install_root.exists():
            self._remove_install_root(swap.install_root)
        if swap.backup_root is not None and swap.backup_root.exists():
            swap.backup_root.replace(swap.install_root)
        shutil.rmtree(swap.stage_dir, ignore_errors=True)

    def uninstall(self, install_root: Path) -> None:
        if not install_root.exists():
            return
        logger.debug(f"Removing extension install directory '{install_root}'")
        try:
            self._remove_install_root(install_root)
        except PermissionError:
            add_pending_deletion(install_root.name, install_root)

    def load_manifest(self, install_root: Path) -> ExtensionManifest | None:
        manifest = load_manifest(install_root)
        if manifest is None:
            raise ValueError(
                f"Manifest '{config.EXTENSIONS.MANIFEST_FILE}' not found in '{install_root}'."
            )
        return manifest

    @staticmethod
    def get_frontend_bundle_info(
        install_root: Path, manifest_json: dict, extension_name: str
    ) -> ExtensionFrontendBundleInfo:
        frontend = manifest_json.get("frontend") or {}
        if not frontend:
            raise FileNotFoundError(f"Расширение '{extension_name}' не имеет фронтенд-бандла.")
        assets_root = ExtensionsInstallManager._build_assets_root(install_root, frontend)
        ExtensionsInstallManager._ensure_assets_root(assets_root, extension_name)
        manifest_entry = frontend.get("entry_file")
        lookup_entry_file = manifest_entry or "index.js"
        bundle_path = ExtensionsInstallManager._resolve_bundle_file(
            assets_root, lookup_entry_file, extension_name
        )
        response_entry_file = manifest_entry or bundle_path.name
        return ExtensionFrontendBundleInfo(
            bundle_path=bundle_path,
            assets_root=assets_root,
            entry_file=response_entry_file,
            entrypoint=frontend.get("entrypoint"),
        )

    @staticmethod
    def resolve_frontend_asset(
        install_root: Path, manifest_json: dict, extension_name: str, asset_path: str
    ) -> Path:
        frontend = manifest_json.get("frontend") or {}
        assets_root = ExtensionsInstallManager._build_assets_root(install_root, frontend)
        ExtensionsInstallManager._ensure_assets_root(assets_root, extension_name)
        target_path = (assets_root / asset_path).resolve()
        ExtensionsInstallManager._ensure_within_root(
            assets_root, target_path, "Неверный путь к файлу фронтенд-ассета."
        )
        if not target_path.exists() or not target_path.is_file():
            raise FileNotFoundError(
                f"Файл фронтенд-ассета '{asset_path}' для '{extension_name}' не найден."
            )
        return target_path

    async def _clone_or_update_repo(self, repository_url: str, install_root: Path) -> None:
        await self.install_from_url(repository_url, install_root)

    def _remove_install_root(self, install_root: Path) -> None:
        shutil.rmtree(install_root, onexc=self._handle_remove_readonly)

    @staticmethod
    def _handle_remove_readonly(function, path, excinfo) -> None:
        error = excinfo if isinstance(excinfo, BaseException) else excinfo[1]
        if not isinstance(error, PermissionError):
            raise error
        target = Path(path)
        if not target.exists():
            raise error
        target.chmod(target.stat().st_mode | stat.S_IWRITE)
        function(path)

    async def _run_command(self, command: list[str]) -> None:
        logger.debug(f"Running extension command: {' '.join(command)}")
        completed = await asyncio.to_thread(
            subprocess.run,
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        logger.debug(
            "Extension command finished rc={} stdout='{}' stderr='{}'",
            completed.returncode,
            (completed.stdout or "").strip(),
            (completed.stderr or "").strip(),
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(stderr or f"Command failed: {' '.join(command)}")

    @staticmethod
    def _build_assets_root(install_root: Path, frontend: dict[str, Any]) -> Path:
        dist_dir = frontend.get("dist_dir") or "frontend/dist"
        return (install_root / dist_dir).resolve()

    @staticmethod
    def _ensure_assets_root(assets_root: Path, extension_name: str) -> None:
        if not assets_root.exists() or not assets_root.is_dir():
            raise FileNotFoundError(
                f"Фронтенд-ассеты расширения '{extension_name}' не найдены."
            )

    @staticmethod
    def _resolve_bundle_file(assets_root: Path, entry_file: str, extension_name: str) -> Path:
        bundle_path = (assets_root / entry_file).resolve()
        ExtensionsInstallManager._ensure_within_root(
            assets_root, bundle_path, "Некорректный путь к фронтенд-бандлу."
        )
        if not bundle_path.exists() or not bundle_path.is_file():
            raise FileNotFoundError(
                f"Фронтенд-бандл '{entry_file}' для '{extension_name}' не найден."
            )
        return bundle_path

    @staticmethod
    def _ensure_within_root(root: Path, target: Path, message: str) -> None:
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError(message) from exc
