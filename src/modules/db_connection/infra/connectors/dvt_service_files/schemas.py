from pydantic import BaseModel, ConfigDict, Field, field_validator


class DVTServiceFilesProperties(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: str = Field(..., description="Organization that owns the stored files")
    project_id: str = Field(..., description="Project that owns the stored files")
    root_prefix: str = Field(default="", description="Optional storage root prefix")

    @field_validator("organization_id", "project_id")
    @classmethod
    def validate_required_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value must not be blank.")
        return normalized

    @field_validator("root_prefix")
    @classmethod
    def normalize_root_prefix(cls, value: str) -> str:
        normalized = value.replace("\\", "/").strip("/")
        if any(part in {"", ".", ".."} for part in normalized.split("/") if part):
            raise ValueError("root_prefix contains an invalid path segment.")
        return normalized


class DVTServiceFilesSecrets(BaseModel):
    model_config = ConfigDict(extra="forbid")
