from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.types import DataFrameMetadata

from .types import SQLStatementCategory, SQLStatementType


class SQLStatementMetadata(BaseModel):
    """Описывает один top-level SQL statement после разбора."""

    model_config = ConfigDict(frozen=True)

    statement_type: SQLStatementType
    category: SQLStatementCategory
    returns_data: bool
    is_query_expression: bool


class SQLCodeMetadata(BaseModel):
    """Содержит итоговый структурный и табличный metadata report по SQL-коду."""

    model_config = ConfigDict(frozen=True)

    statements: tuple[SQLStatementMetadata, ...]
    statement_count: int = Field(ge=0)
    result_statement_count: int = Field(ge=0)
    dialect_name: str | None = None
    dataframe_metadata: DataFrameMetadata | None = None
    dataframe_metadata_statement_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_consistency(self) -> "SQLCodeMetadata":
        expected_statement_count = len(self.statements)
        if self.statement_count != expected_statement_count:
            raise ValueError(
                f"statement_count={self.statement_count} does not match statements={expected_statement_count}."
            )

        expected_result_statement_count = sum(1 for statement in self.statements if statement.returns_data)
        if self.result_statement_count != expected_result_statement_count:
            raise ValueError(
                "result_statement_count does not match the number of result-returning statements."
            )

        if self.dataframe_metadata is None and self.dataframe_metadata_statement_index is not None:
            raise ValueError(
                "dataframe_metadata_statement_index must be null when dataframe_metadata is absent."
            )

        if self.dataframe_metadata_statement_index is not None and (
            self.dataframe_metadata_statement_index >= expected_statement_count
        ):
            raise ValueError("dataframe_metadata_statement_index is out of range.")

        return self
