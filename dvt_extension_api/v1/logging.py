"""Logging facade for extension code."""

from src.logger import logger as _dvt_logger


def get_logger(**context):
    """Return the DVT logger, optionally bound to structured context."""
    return _dvt_logger.bind(**context) if context else _dvt_logger


logger = get_logger()

__all__ = ["get_logger", "logger"]
