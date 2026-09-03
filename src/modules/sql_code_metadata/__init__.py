"""Bounded context для анализа SQL-кода и извлечения метаданных."""

from .domain import (
    SQLCodeMetadata,
    SQLCodeMetadataDomainError,
    SQLCodeMetadataError,
    SQLStatementCategory,
    SQLStatementMetadata,
    SQLStatementType,
    SQLValidationError,
    SQLValidationPolicy,
)
from .flow import SQLCodeMetadataProvider, ExtractSQLCodeMetadataUseCase, ValidateSQLUseCase
from .infra import SQLAlchemyResultMetadataGateway, SQLGlotParserGateway

__all__ = [
    "ExtractSQLCodeMetadataUseCase",
    "SQLAlchemyResultMetadataGateway",
    "SQLCodeMetadata",
    "SQLCodeMetadataDomainError",
    "SQLCodeMetadataError",
    "SQLCodeMetadataProvider",
    "SQLGlotParserGateway",
    "SQLStatementCategory",
    "SQLStatementMetadata",
    "SQLStatementType",
    "SQLValidationError",
    "SQLValidationPolicy",
    "ValidateSQLUseCase",
]
