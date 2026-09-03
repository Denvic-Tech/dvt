import hashlib
import logging
import platform
import uuid
from pathlib import Path

import config


class WorkerIDManager:
    """
    HWID + Worker ID менеджер:

    - Windows: MachineGuid через реестр
    - Linux: /etc/machine-id
    - HWID хранится в системной папке
    - При отсутствии файла сначала используется общий HWID-генератор
    """

    def __init__(self, app_name: str = "DVT"):
        self.app_name = app_name
        self.storage_path = config.PROJECT.HWID_PATH
        self.storage_path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    async def get_windows_machine_guid_winreg() -> str:
        if platform.system().lower() != "windows":
            return ""
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography"
            )
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value).strip()
        except PermissionError:
            logging.warning("Нет прав на чтение MachineGuid из реестра")
        except Exception as e:
            logging.warning(f"Ошибка чтения MachineGuid: {e}")
        return ""

    @staticmethod
    async def get_linux_machine_id() -> str:
        p = Path("/etc/machine-id")
        if p.exists():
            try:
                return p.read_text().strip()
            except:
                pass

        # fallback
        p = Path("/proc/sys/kernel/random/boot_id")
        if p.exists():
            try:
                return p.read_text().strip()
            except:
                pass
        return ""

    async def get_hwid(self) -> str:
        hwid_file = self.storage_path / "hwid.id"
        hwid = self._read_hwid_from_file(hwid_file)
        if hwid:
            return hwid

        hwid = self._generate_hwid_with_shared_generator()
        if hwid:
            self._write_hwid_to_file(hwid_file, hwid)
            return hwid

        system = platform.system().lower()
        machine_fingerprint = ""

        if "windows" in system:
            logging.info("Windows machine-id detected")
            machine_fingerprint = await self.get_windows_machine_guid_winreg()
        elif "linux" in system:
            logging.info("Linux machine-id detected")
            machine_fingerprint = await self.get_linux_machine_id()

        # fallback на случай отсутствия machine-id
        if not machine_fingerprint:
            logging.warning("Machine ID не найден, генерируется случайный HWID")
            machine_fingerprint = str(uuid.uuid4())

        hwid = hashlib.sha256(machine_fingerprint.encode()).hexdigest()
        self._write_hwid_to_file(hwid_file, hwid)
        return hwid

    async def get_or_create_worker_id(self) -> str:
        return await self.get_hwid()

    @staticmethod
    def _running_in_docker() -> bool:
        if Path("/.dockerenv").exists():
            return True
        try:
            with open("/proc/1/cgroup") as f:
                content = f.read()
                return "docker" in content or "kubepods" in content
        except:
            return False

    @staticmethod
    def _read_hwid_from_file(hwid_file: Path) -> str:
        if not hwid_file.exists():
            return ""

        try:
            return hwid_file.read_text().strip()
        except Exception as exc:
            logging.warning(f"Не удалось прочитать HWID из файла {hwid_file}: {exc}")
            return ""

    @staticmethod
    def _write_hwid_to_file(hwid_file: Path, hwid: str) -> None:
        hwid_file.write_text(hwid)

    @staticmethod
    def _generate_hwid_with_shared_generator() -> str:
        try:
            hwid_generator = WorkerIDManager._load_shared_hwid_generator()
            hwid = hwid_generator()
        except KeyboardInterrupt:
            raise
        except BaseException as exc:
            logging.warning(f"Не удалось сгенерировать HWID через src.security.hwid: {exc}")
            return ""

        if not hwid:
            logging.warning("src.security.hwid вернул пустой HWID")
            return ""

        return hwid.strip()

    @staticmethod
    def _load_shared_hwid_generator():
        from src.security.hwid import generate_hwid

        return generate_hwid
