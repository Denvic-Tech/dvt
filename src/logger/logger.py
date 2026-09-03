import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, List, Union

from loguru import logger as loguru_logger

from src.logger._multiprocessing.mp_bridge import MP_LOG_BRIDGE_EXTRA_KEY
from src.logger.config import get_logging_config
from src.logger.memory_buffer import log_memory_buffer

if TYPE_CHECKING:
    from src.logger.db_sink import BatchedDBSink

import config

DB_SINK: Union["BatchedDBSink", None] = None
DB_SINK_HANDLER_ID: int | None = None


def _console_sink_filter(record) -> bool:
    return not bool(record["extra"].get(MP_LOG_BRIDGE_EXTRA_KEY))


def setup_logger(
        level: str = "DEBUG",
        intercept_standard_logging: bool = False,
        log_to_file: bool = False,
        level_to_file: str = "DEBUG",
        logs_dir: str = "logs",
        log_filename: str = "etl_services.log",
        console_backtrace: bool = False,
        console_diagnose: bool = False,
        console_enqueue: bool = False,
        add_console: bool = True,
):
    cfg = get_logging_config()

    loguru_logger.remove()

    if add_console:
        console_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        )
        loguru_logger.add(
            sys.stderr,
            level=level.upper(),
            colorize=True,
            format=console_format,
            backtrace=console_backtrace,
            diagnose=console_diagnose,
            enqueue=console_enqueue,
            filter=_console_sink_filter,
        )

    memory_format = "{message}"
    try:
        loguru_logger.add(
            log_memory_buffer,
            level=level.upper(),
            enqueue=True,
            format=memory_format,
            colorize=False
        )
    except PermissionError:
        # Fallback when multiprocessing queue is not permitted (e.g., locked down test env)
        loguru_logger.add(
            log_memory_buffer,
            level=level.upper(),
            enqueue=False,
            format=memory_format,
            colorize=False
        )

    if log_to_file:
        try:
            logs_path = Path(logs_dir)
            logs_path.mkdir(parents=True, exist_ok=True)
            log_file_path = logs_path / log_filename
            file_format = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
            loguru_logger.add(
                log_file_path, rotation="10 MB", retention="7 days", compression="zip",
                level=level_to_file, encoding="utf-8", format=file_format,
                enqueue=True,
                backtrace=True,
                diagnose=True,
                catch=True
            )
            loguru_logger.info(f"Logging to file enabled: {log_file_path}")
        except Exception as e:
            loguru_logger.error(f"Failed to configure file logging to '{logs_dir}/{log_filename}': {e}")

    if intercept_standard_logging:
        from src.logger.intercept_handler import InterceptHandler

        # Перехват всего stdlib-логирования
        logging.captureWarnings(True)  # warnings.warn -> logging.WARNING -> Loguru
        logging.basicConfig(handlers=[InterceptHandler(logger=loguru_logger)], level=0, force=True)

        # При необходимости поджать конкретные логгеры (пример):
        for module, module_cfg in cfg.get("loggers", {}).items():
            lg = logging.getLogger(module)

            if "level" in module_cfg:
                module_level = logging.getLevelName(module_cfg["level"].upper())
                lg.setLevel(module_level)

            lg.handlers = [InterceptHandler(logger=loguru_logger)]
            lg.propagate = False  # чтобы не дублировалось

    loguru_logger.info(f"Logger configured with level: {level.upper()}")
    return loguru_logger


logger = setup_logger(
    level=config.LOGGING.LOG_LEVEL,
    log_to_file=config.LOGGING.LOG_TO_FILE,
    level_to_file=config.LOGGING.LOG_LEVEL_TO_FILE,
    intercept_standard_logging=config.LOGGING.INTERCEPT_STANDARD_LOGGING,
)

STARTUP_WARNINGS: List[str] = []


def log_startup_warning(msg: str):
    logger.warning(msg)
    STARTUP_WARNINGS.append(msg)


def print_startup_warnings():
    if STARTUP_WARNINGS:
        logger.warning("--- Startup Warnings ---")
        for s in STARTUP_WARNINGS: logger.warning(s)
        logger.warning("--- End Startup Warnings ---")
        STARTUP_WARNINGS.clear()
