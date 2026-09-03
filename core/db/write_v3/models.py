from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class WriteRequest(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    mode: WriteMode
    target: WriteTarget
    chunksize: int | None = Field(default=1000, ge=1)
    write_workers: int = Field(default=1, ge=1)
    upsert: UpsertConfig | None = None
    on_extra_df_columns: ExtraColumnsMode = ExtraColumnsMode.ERROR
    on_missing_df_columns: MissingColumnsMode = MissingColumnsMode.IGNORE_IF_DEFAULT

    @model_validator(mode="after")
    def _validate_request(self) -> "WriteRequest":
        if self.mode == WriteMode.UPSERT and self.upsert is None:
            raise ValueError("upsert config is required for mode='upsert'.")
        if self.mode != WriteMode.UPSERT and self.upsert is not None:
            raise ValueError("upsert config is allowed only for mode='upsert'.")
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
