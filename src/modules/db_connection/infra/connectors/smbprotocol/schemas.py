from pydantic import BaseModel, ConfigDict, Field, field_validator


class SMBProtocolProperties(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(..., description="SMB server hostname or IP address")
    port: int = Field(..., description="SMB server port")
    share: str = Field(..., description="Shared folder name")
    username: str = Field(..., description="Username used to authenticate")

    @field_validator("host", "share", "username")
    @classmethod
    def validate_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value must not be blank.")
        return normalized


class SMBProtocolSecrets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(..., description="Password used to authenticate")

    @field_validator("password")
    @classmethod
    def validate_password_not_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("Password must not be blank.")
        return value
