from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from src.node_dsl.core.input_values import NodeInputConstantValue, NodeInputExpressionValue

ConnectionOverrideStringValue: TypeAlias = str | NodeInputExpressionValue | NodeInputConstantValue
ConnectionOverrideBooleanValue: TypeAlias = bool | NodeInputExpressionValue | NodeInputConstantValue


class S3ConnectionOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["s3"] = "s3"
    bucket: ConnectionOverrideStringValue | None = None
    prefix: ConnectionOverrideStringValue | None = None
    verify: ConnectionOverrideBooleanValue | None = Field(
        default=None,
        description="Verify SSL certificates. Uses the connection value when omitted.",
    )


class FTPConnectionOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["ftp"] = "ftp"
    initial_directory: ConnectionOverrideStringValue | None = None


class SFTPConnectionOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["sftp"] = "sftp"
    initial_directory: ConnectionOverrideStringValue | None = None


FileConnectionOverridesInput: TypeAlias = (
    S3ConnectionOverrides
    | FTPConnectionOverrides
    | SFTPConnectionOverrides
)
FileConnectionOverridesConfig = Annotated[
    FileConnectionOverridesInput,
    Field(discriminator="type"),
]

_FILE_CONNECTION_OVERRIDES_ADAPTER = TypeAdapter(FileConnectionOverridesConfig)


@dataclass(frozen=True, slots=True)
class ResolvedS3ConnectionOverrides:
    type: Literal["s3"] = "s3"
    bucket: str | None = None
    prefix: str | None = None
    verify: bool | None = None


@dataclass(frozen=True, slots=True)
class ResolvedFTPConnectionOverrides:
    type: Literal["ftp"] = "ftp"
    initial_directory: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedSFTPConnectionOverrides:
    type: Literal["sftp"] = "sftp"
    initial_directory: str | None = None


ResolvedFileConnectionOverrides: TypeAlias = (
    ResolvedS3ConnectionOverrides
    | ResolvedFTPConnectionOverrides
    | ResolvedSFTPConnectionOverrides
)


def parse_file_connection_overrides(payload: object) -> FileConnectionOverridesInput:
    return _FILE_CONNECTION_OVERRIDES_ADAPTER.validate_python(payload)
