from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class SQLValidationPolicy(BaseModel):
    """Описывает явные правила структурной SQL-валидации."""

    model_config = ConfigDict(frozen=True)

    forbid_ddl_statements: bool = False
    forbid_data_mutating_statements: bool = False

    allow_multiple_statements: bool = True
    allow_multiple_result_statements: bool = False

    require_result_statement: bool = False
    require_single_result_statement: bool = False

    validate_parseability: bool = True

    allowed_statement_types: set[str] | None = None
    forbidden_statement_types: set[str] | None = None

    @field_validator("allowed_statement_types", "forbidden_statement_types")
    @classmethod
    def normalize_statement_types(cls, value: set[str] | None) -> set[str] | None:
        if value is None:
            return None

        normalized = {item.strip().upper() for item in value if item and item.strip()}
        return normalized or None

    @model_validator(mode="after")
    def validate_type_overlaps(self) -> "SQLValidationPolicy":
        if not self.allowed_statement_types or not self.forbidden_statement_types:
            return self

        overlap = self.allowed_statement_types & self.forbidden_statement_types
        if overlap:
            overlap_value = ", ".join(sorted(overlap))
            raise ValueError(f"Statement types cannot be both allowed and forbidden: {overlap_value}.")

        return self
