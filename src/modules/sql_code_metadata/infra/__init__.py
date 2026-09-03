"""Infra-адаптеры анализа SQL-кода."""

from .sqlalchemy_result_metadata import SQLAlchemyResultMetadataGateway
from .sqlglot_parser import SQLGlotParserGateway

__all__ = ["SQLAlchemyResultMetadataGateway", "SQLGlotParserGateway"]
