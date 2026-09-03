"""Утилиты для работы с расширениями."""
import os

from sqlmodel import select

from src.db import AsyncSessionLocal
from src.extensions.errors import stage_error
from src.logger import logger
from src.models.extension import ExtensionRecord
from src.node_dsl.registry import definitions as definitions_registry
from src.pipeline.types import Pipeline


def lock_file(file):
    if os.name == 'nt':  # Windows
        import msvcrt
        # Перемещаем указатель в начало и блокируем 1 байт
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, 1)
    else:  # Unix (Linux/Mac)
        import fcntl
        fcntl.flock(file, fcntl.LOCK_EX)

def unlock_file(file):
    if os.name == 'nt':  # Windows
        import msvcrt
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:  # Unix
        import fcntl
        fcntl.flock(file, fcntl.LOCK_UN)

def collect_extension_names(pipeline: Pipeline) -> set[str]:
    """Собирает имена расширений, используемых в пайплайне.

    Args:
        pipeline: Словарь {node_id: NodeData} с узлами пайплайна.

    Returns:
        Множество имен расширений, которые используются в узлах пайплайна.
    """
    extension_names: set[str] = set()
    for node in pipeline.values():
        node_name = getattr(node, "name", None)
        if not node_name:
            continue
        try:
            node_def = definitions_registry.get(node_name)
        except Exception:
            continue
        if node_def.extension_name:
            extension_names.add(node_def.extension_name)
    return extension_names


async def ensure_extension_deps_installed(*, raise_on_failure: bool = False) -> None:
    """Устанавливает зависимости расширений локально в текущей среде.

    ``raise_on_failure`` используется execution barrier Task Worker: в этом режиме
    локальная установка обязана завершиться успешно до reload node registry.
    """
    from src.managers.extension_db_manager import ExtensionDBManager
    from src.managers.extension_dependency_manager import ExtensionDependencyManager

    async def persist_dependency_error(
        extension_name: str,
        error_message: str | None,
        *,
        clear_only_dependency_error: bool = False,
    ) -> None:
        async with AsyncSessionLocal() as session:
            db_manager = ExtensionDBManager(session)
            current = await db_manager.get_extension(extension_name)
            if current is None:
                return
            if clear_only_dependency_error and not (
                current.error_message
                and current.error_message.startswith("Dependency installation failed:")
            ):
                return
            await db_manager.set_runtime_error(current, error_message)

    # Определяем путь к файлу блокировки в зависимости от ОС
    if os.name == 'nt':
        # Для Windows используем временную папку пользователя
        lock_path = os.path.join(os.environ.get('TEMP', 'C:\\Temp'), 'extension_deps.lock')
        # Убедимся, что папка существует
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    else:
        # Для Unix
        lock_path = '/tmp/extension_deps.lock'

    try:
        # Открываем файл (режим 'a' создаст файл, если его нет, и не очистит его)
        with open(lock_path, 'a') as f:
            logger.debug(f"Waiting for lock on {lock_path}...")

            # БЛОКИРОВКА: Здесь процесс замрет, если другой воркер уже занят установкой
            lock_file(f)

            try:
                logger.info("Local lock acquired. Starting dependency installation...")

                # Теперь мы внутри "критической секции". Выполняем работу с БД.
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(ExtensionRecord).where(ExtensionRecord.is_installed == True)
                    )
                    extensions = result.scalars().all()

                dependency_manager = ExtensionDependencyManager()
                failures: list[str] = []
                for extension in extensions:
                    try:
                        # ВАЖНО: внутри install_dependencies обязательно должна быть
                        # проверка, нужно ли реально что-то ставить (например через pip check),
                        # чтобы второй воркер не переустанавливал то, что уже поставил первый.
                        res = await dependency_manager.install_dependencies(extension.name)

                        if res.success:
                            logger.info(f"Extension '{extension.name}' deps ready.")
                            await persist_dependency_error(
                                extension.name,
                                None,
                                clear_only_dependency_error=True,
                            )
                        else:
                            message = f"Extension '{extension.name}' failure: {res.error_message}"
                            logger.error(message)
                            failures.append(message)
                            await persist_dependency_error(
                                extension.name,
                                stage_error(
                                    "Dependency installation failed",
                                    res.error_message
                                    or "unknown dependency installation error",
                                ),
                            )

                    except Exception as exc:
                        message = f"Error installing '{extension.name}': {exc}"
                        logger.warning(message)
                        failures.append(message)
                        await persist_dependency_error(
                            extension.name,
                            stage_error("Dependency installation failed", exc),
                        )

                if failures and raise_on_failure:
                    raise RuntimeError("; ".join(failures))

            finally:
                # РАЗБЛОКИРОВКА: В любом случае снимаем замок
                unlock_file(f)
                logger.debug("Local lock released.")

    except Exception as exc:
        logger.warning(f"Failed to manage lock or install extension deps: {exc}")
        if raise_on_failure:
            raise