from __future__ import annotations

from typing import Protocol

from sqlalchemy.engine import Engine

from core.types import DataFrameMetadata

from .parser import ParsedSQLStatement


class SQLResultMetadataGateway(Protocol):
    """Описывает контракт извлечения DataFrameMetadata для result-returning statement."""

    def build_dataframe_metadata(
        self,
        *,
        parsed_statement: ParsedSQLStatement,
        dialect_name: str | None,
        connection: Engine,
    ) -> DataFrameMetadata:
        """Строит DataFrameMetadata для конкретного result-returning statement."""
