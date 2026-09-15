"""Stable public facade for Parquet filename templates."""

from core.parquet.write.naming import (
    DEFAULT_ADVANCED_TEMPLATE,
    FilenameTemplate,
    NamingContext,
)

__all__ = [
    "DEFAULT_ADVANCED_TEMPLATE",
    "FilenameTemplate",
    "NamingContext",
]
