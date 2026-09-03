from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.types import DataType


class WriteMode(str, Enum):
    APPEND = "append"
    TRUNCATE = "truncate"
    UPSERT = "upsert"


class ExtraColumnsMode(str, Enum):
    IGNORE = "ignore"
    ERROR = "error"


class MissingColumnsMode(str, Enum):
    IGNORE = "ignore"
    IGNORE_IF_DEFAULT = "ignore_if_default"
    ERROR = "error"


class UpsertConfig(BaseModel):
    key_column: str


class WriteTarget(BaseModel):
    table_name: str
    schema_name: str | None = None
    database_name: str | None = None


class WriteColumnMapping(BaseModel):
    source_name: str = Field(min_length=1)
    target_name: str = Field(min_length=1)
    dtype: DataType | str | None = None
    nullable: bool | None = None

    @field_validator("source_name", "target_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("column mapping names must not be empty.")
        return normalized

    @field_validator("dtype", mode="before")
    @classmethod
    def _normalize_dtype(cls, value: object) -> object:
        if value is None or isinstance(value, DataType):
            return value
        if isinstance(value, str):
            try:
                return DataType(value)
            except ValueError:
                return DataType.from_type(value)
        return value


class WriteRequest(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    mode: WriteMode
    target: WriteTarget
    chunksize: int | None = Field(default=1000, ge=1)
    write_workers: int = Field(default=1, ge=1)
    upsert: UpsertConfig | None = None
    on_extra_df_columns: ExtraColumnsMode = ExtraColumnsMode.ERROR
    on_missing_df_columns: MissingColumnsMode = MissingColumnsMode.IGNORE_IF_DEFAULT
    column_mapping: list[WriteColumnMapping] | None = None

    @model_validator(mode="after")
    def _validate_request(self) -> "WriteRequest":
        if self.mode == WriteMode.UPSERT and self.upsert is None:
            raise ValueError("upsert config is required for mode='upsert'.")
        if self.mode != WriteMode.UPSERT and self.upsert is not None:
            raise ValueError("upsert config is allowed only for mode='upsert'.")
        if self.column_mapping:
            source_names = [mapping.source_name for mapping in self.column_mapping]
            duplicate_sources = _find_duplicates(source_names)
            if duplicate_sources:
                raise ValueError(
                    "column_mapping contains duplicate source_name values: "
                    f"{duplicate_sources!r}."
                )

            target_names = [mapping.target_name.lower() for mapping in self.column_mapping]
            duplicate_targets = _find_duplicates(target_names)
            if duplicate_targets:
                raise ValueError(
                    "column_mapping contains duplicate target_name values "
                    f"(case-insensitive): {duplicate_targets!r}."
                )
        return self


class WritePlan(BaseModel):
    dialect: str
    mode: WriteMode
    table_exists: bool
    target: WriteTarget
    use_staging: bool = False
    upsert_key: str | None = None


class WriteDiagnostic(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class WriteResult(BaseModel):
    mode: WriteMode
    target_name: str
    rows_written: int
    staging_rows: int = 0
    diagnostics: list[WriteDiagnostic] = Field(default_factory=list)


def _find_duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)
