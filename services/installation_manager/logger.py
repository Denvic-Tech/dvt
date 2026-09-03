import logging
import os
import sys


def _resolve_log_level() -> int:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, level_name, logging.INFO)


def _configure_logger(logger_name: str) -> logging.Logger:
    logging.basicConfig(
        level=_resolve_log_level(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    logger = logging.getLogger(logger_name)
    logger.setLevel(_resolve_log_level())
    return logger


logger = _configure_logger("installation_manager")
