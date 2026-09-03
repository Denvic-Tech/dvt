import math
import platform
import time

import psutil

from src.schemas.http.system import SystemInfo


def format_uptime(seconds: float) -> str:
    """Форматирует время в секундах в читаемый формат D days, H hours, M minutes, S seconds."""
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{int(days)} days")
    if hours:
        parts.append(f"{int(hours)} hours")
    if minutes:
        parts.append(f"{int(minutes)} minutes")
    # Добавляем секунды только если нет более крупных единиц или если время меньше минуты
    if seconds or not parts:
        parts.append(f"{int(seconds)} seconds")

    return ", ".join(parts)


def format_bytes(byte_count: int, decimal_places: int = 2) -> str:
    """
    Форматирует количество байт в читаемый формат с использованием единиц измерения.
    """
    if byte_count is None:
        return "N/A"
    if byte_count < 0:
        return "Invalid size"
    if byte_count == 0:
        return "0 Bytes"

    base = 1024
    units = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB']
    unit_index = min(math.floor(math.log(byte_count, base)), len(units) - 1)
    formatted_value = byte_count / (base ** unit_index)

    return f"{formatted_value:.{decimal_places}f} {units[unit_index]}"


class SystemInfoManager:
    """
    Класс для получения системной информации.
    """

    def __init__(self):
        self.start_time = time.time()
        self.system_boot_time = psutil.boot_time()

        self.hostname = platform.node()
        self.os_type = platform.system()
        self.os_release = platform.release()
        self.os_version = platform.version()

        self.cpu_cores_physical = psutil.cpu_count(logical=False)
        self.cpu_cores_logical = psutil.cpu_count(logical=True)

        self.network_io = psutil.net_io_counters()

    def get_system_info(self) -> SystemInfo:
        """
        Собирает и возвращает системную информацию в виде Pydantic модели SystemInfo.

        :return: Экземпляр Pydantic модели SystemInfo.
        """
        # Время работы (uptime)
        current_time_timestamp = time.time()
        system_uptime_seconds = current_time_timestamp - self.system_boot_time
        system_uptime_formatted = format_uptime(system_uptime_seconds)
        app_uptime_seconds = current_time_timestamp - self.start_time
        app_uptime_formatted = format_uptime(app_uptime_seconds)

        # Информация о CPU
        # cpu_percent(interval=1) блокирует на 1 секунду для получения среднего значения
        # Если нужно мгновенное значение, используйте interval=0, но оно менее показательно
        cpu_percent = psutil.cpu_percent(interval=0.1)  # Небольшой интервал для более точного мгновенного значения

        # Информация о RAM
        virtual_mem = psutil.virtual_memory()

        # Информация о диске (для корневой файловой системы '/')
        # В Docker контейнере '/' обычно соответствует файловой системе контейнера
        try:
            disk_usage = psutil.disk_usage('/')
            disk_total = disk_usage.total
            disk_used = disk_usage.used
            disk_free = disk_usage.free
            disk_used_percent = disk_usage.percent
        except Exception as e:
            # Обработка случаев, когда '/' недоступен или есть другие ошибки
            print(f"Error getting disk info for '/': {e}")
            disk_total = 0.0
            disk_used = 0.0
            disk_free = 0.0
            disk_used_percent = 0.0

        network_io = psutil.net_io_counters()

        system_info = SystemInfo(
            hostname=self.hostname,

            os_type=self.os_type,
            os_release=self.os_release,
            os_version=self.os_version,

            system_uptime_seconds=system_uptime_seconds,
            app_uptime_seconds=app_uptime_seconds,

            cpu_percent=cpu_percent,
            cpu_cores_physical=self.cpu_cores_physical,
            cpu_cores_logical=self.cpu_cores_logical,

            ram_total=virtual_mem.total,
            ram_available=virtual_mem.available,
            ram_used=virtual_mem.used,
            ram_used_percent=virtual_mem.percent,

            disk_total=disk_total,
            disk_used=disk_used,
            disk_free=disk_free,
            disk_used_percent=disk_used_percent,

            network_bytes_sent=network_io.bytes_sent,
            network_bytes_recv=network_io.bytes_recv,
            process_count=len(psutil.pids())
        )

        return system_info


# 3. Пример использования (можно запустить этот файл напрямую для проверки)
if __name__ == "__main__":
    manager = SystemInfoManager()
    info = manager.get_system_info()

    # Выводим информацию
    print("--- System Information ---")
    print(f"Hostname: {info.hostname}")
    print(f"OS: {info.os_type} {info.os_release} ({info.os_version})")
    print(f"System Uptime: {format_uptime(info.system_uptime_seconds)} ({info.system_uptime_seconds:.2f} seconds)")
    print(f"App Uptime: {format_uptime(info.app_uptime_seconds)} ({info.app_uptime_seconds:.2f} seconds)")
    print(f"CPU Usage: {info.cpu_percent:.1f}%")
    print(f"CPU Cores (Physical): {info.cpu_cores_physical}")
    print(f"CPU Cores (Logical): {info.cpu_cores_logical}")
    print(f"RAM Total: {info.ram_total:.2f} GB")
    print(f"RAM Available: {info.ram_available:.2f} GB")
    print(f"RAM Used: {info.ram_used:.2f} GB ({info.ram_used_percent:.1f}%)")
    print(f"Disk Total ('/'): {info.disk_total:.2f} GB")
    print(f"Disk Used ('/'): {info.disk_used:.2f} GB ({info.disk_used_percent:.1f}%)")
    print(f"Disk Free ('/'): {info.disk_free:.2f} GB")
    print(f"Network Sent: {format_bytes(info.network_bytes_sent)} ({info.network_bytes_sent} bytes)")
    print(f"Network Received: {format_bytes(info.network_bytes_recv)} ({info.network_bytes_recv} bytes)")
    print(f"Process Count: {info.process_count}")

    # Можно также получить информацию как словарь или JSON
    print("\n--- As Dictionary ---")
    print(info.model_dump())

    print("\n--- As JSON ---")
    print(info.model_dump_json(indent=2))
