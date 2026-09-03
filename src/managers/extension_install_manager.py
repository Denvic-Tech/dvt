import asyncio
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

import config
from src.extensions.deletion_queue import add_pending_deletion
from src.extensions.loader import load_manifest, load_manifest_payload
from src.logger import logger
from src.managers.extension_dependency_manager import get_dependency_manager
from src.types import ExtensionManifest


@dataclass
class ExtensionFrontendBundleInfo:
    bundle_path: Path
    assets_root: Path
    entry_file: str
    entrypoint: str | None


async def load_manifest_from_repository(repository_url: str) -> ExtensionManifest | None:
    """Загружает манифест расширения из zip-архива по URL."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(repository_url)
            resp.raise_for_status()

        with tempfile.TemporaryDirectory(prefix="dvt-extension-manifest-") as tmp_dir:
            tmp_path = Path(tmp_dir)

            with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                z.extractall(tmp_path)

            extracted_items = list(tmp_path.iterdir())
            root = (
                extracted_items[0]
                if len(extracted_items) == 1 and extracted_items[0].is_dir()
                else tmp_path
            )

            return load_manifest_payload(root)

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

    async def install_from_url(self, repository_url: str, install_root: Path) -> None:
        install_root.parent.mkdir(parents=True, exist_ok=True)
        logger.debug(
            f"Installing extension from '{repository_url}' into '{install_root}'"
        )
        await self._clone_or_update_repo(repository_url, install_root)

    async def install_requirements(self, install_root: Path) -> None:
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
                f"Invalid [project].dependencies in '{pyproject_path}': expected list, got {type(dependencies).__name__}"
            )
            raise ValueError("Invalid [project].dependencies in pyproject.toml")

        requirements = [item for item in dependencies if isinstance(item, str) and item.strip()]
        if not requirements:
            logger.debug(f"No [project].dependencies found for extension in '{install_root}'")
            return

        logger.debug(
            f"Installing extension dependencies from '{pyproject_path}' into the current Python environment"
        )

        await self._run_command(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                *requirements,
            ]
        )

        logger.debug("Successfully installed extension dependencies")

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
            raise ValueError(f"Manifest '{config.EXTENSIONS.MANIFEST_FILE}' not found in '{install_root}'.")
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
        logger.debug(f"Downloading extension from '{repository_url}' into '{install_root}'")

        if install_root.exists():
            try:
                self._remove_install_root(install_root)
            except PermissionError:
                add_pending_deletion(install_root.name, install_root)
                raise

        install_root.parent.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            tmp_file_path = None
            try:
                tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
                tmp_file_path = Path(tmp_file.name)
                tmp_file.close()

                async with client.stream("GET", repository_url) as resp:
                    resp.raise_for_status()

                    content_length = resp.headers.get("Content-Length")
                    if content_length and int(content_length) > 200 * 1024 * 1024:
                        raise ValueError("Archive too large")

                    async for chunk in resp.aiter_bytes():
                        with open(tmp_file_path, "ab") as f:
                            f.write(chunk)

                with tempfile.TemporaryDirectory(prefix="ext-install-") as tmp_dir:
                    tmp_path = Path(tmp_dir)

                    logger.debug(f"Downloaded archive size: {tmp_file_path.stat().st_size}")

                    with open(tmp_file_path, "rb") as f:
                        head = f.read(200)
                        logger.debug(f"Archive head bytes: {head[:200]}")

                    with zipfile.ZipFile(tmp_file_path, "r") as z:
                        self._safe_extract_zip(z, tmp_path)

                    items = list(tmp_path.iterdir())
                    if len(items) == 1 and items[0].is_dir():
                        source_root = items[0]
                    else:
                        source_root = tmp_path

                    shutil.move(str(source_root), str(install_root))

            finally:
                if tmp_file_path and tmp_file_path.exists():
                    try:
                        tmp_file_path.unlink(missing_ok=True)
                    except Exception:
                        logger.warning(f"Failed to remove temp archive '{tmp_file_path}'")

    def _safe_extract_zip(self, zip_file: zipfile.ZipFile, target_dir: Path) -> Path:
        for member in zip_file.infolist():
            member_path = target_dir / member.filename
            if not str(member_path.resolve()).startswith(str(target_dir.resolve())):
                raise ValueError(f"Unsafe archive content detected: {member.filename}")

        zip_file.extractall(target_dir)

        items = list(target_dir.iterdir())
        if len(items) == 1 and items[0].is_dir():
            return items[0]
        return target_dir

    def _remove_install_root(self, install_root: Path) -> None:
        shutil.rmtree(install_root, onexc=self._handle_remove_readonly)

    @staticmethod
    def _handle_remove_readonly(function, path, excinfo) -> None:
        error = excinfo if isinstance(excinfo, BaseException) else excinfo[1]
        if not isinstance(error, PermissionError):
            raise error

        if not Path(path).exists():
            raise error

        os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)
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
            f"Extension command finished rc={completed.returncode} stdout='{(completed.stdout or '').strip()}' stderr='{(completed.stderr or '').strip()}'"
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
