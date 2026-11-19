"""Wire contracts shared by the protected manager and Gateway."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[a-f0-9]{64}$")]
Revision = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{4,32}$")]
VersionText = Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+(?:-?rc[1-9]\d*)?$")]
OperationStage = Literal[
    "admitted", "preparing", "prepared", "maintenance", "backup", "migrating",
    "applying", "verifying", "resuming", "recovery_required", "recovering",
    "succeeded", "cancelled", "failed",
]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SourceFacts(BaseModel):
    version: str
    revision: str


class SelectRelease(WireModel):
    version: VersionText
    manifest_digest: Digest
    confirm_rc: bool = False


class InstallRequest(SelectRelease):
    kind: Literal["install"]
    app_port: Annotated[int, Field(ge=1, le=65535)] | None = None
    task_workers_count: Annotated[int, Field(ge=1)] = 4
    install_dir: str | None = Field(default=None, max_length=4096)
    public_urls: list[Annotated[str, Field(max_length=512)]] | None = Field(
        default=None, min_length=1, max_length=32,
    )
    ai_mcp_enabled: bool = False


class UpdateRequest(SelectRelease):
    kind: Literal["update"]


class ReleaseOption(BaseModel):
    version: str
    channel: Literal["stable", "rc"]
    manifest_digest: Digest


class CatalogView(BaseModel):
    catalog_fetched_at: str | None
    catalog_error: str | None
    source_error: str | None
    source: SourceFacts | None
    trust_configured: bool
    releases: list[ReleaseOption]
    recommended_stable: ReleaseOption | None
    paths: dict[str, list[str]]
    first_steps: dict[str, ReleaseOption]


class OperatorAction(StrEnum):
    APPLY = "apply"
    RESUME = "resume"
    CANCEL_PREPARATION = "cancel_preparation"
    EXTEND_MAINTENANCE = "extend_maintenance"
    DEFER_MAINTENANCE = "defer_maintenance"
    RECOVER_MANAGER = "recover_manager"
    RETURN_TO_SOURCE = "return_to_source"
    RESTORE_START = "restore_start"


class ActionConfirmation(WireModel):
    confirm: bool = False


class OperationPlan(BaseModel):
    source_version: str | None
    source_revision: str | None
    target_revision: Revision
    add: list[str]
    recreate: list[str]
    retire: list[str]
    profiles: list[str]
    migration: Literal["from_revision", "none"] | None
    rollback: Literal["restore_backup", "compatible_apps"] | None
    target_version: str
    pull_and_unpack_bytes: int
    data_reserve_bytes: int
    maintenance_drain_seconds: int
    schedule_policy: Literal["skip_cron_preserve_existing_retries"]
    queue_policy: Literal["drain_admitted_cancel_unadmitted_roots"]


class OperationView(BaseModel):
    id: UUID
    kind: Literal["install", "update", "manager_recovery", "restore"]
    version: str
    manifest_digest: Digest
    stage: OperationStage
    failure: str | None
    actions: list[OperatorAction]
    plan: OperationPlan | None
    created_at: datetime
    finished_at: datetime | None


class BrowserPairing(WireModel):
    code: Annotated[SecretStr, Field(min_length=43, max_length=43)]


class PairingCode(BaseModel):
    code: str
