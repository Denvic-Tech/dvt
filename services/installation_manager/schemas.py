from pydantic import BaseModel, Field


class InstallRequest(BaseModel):
    version: str = "latest"
    public_urls: list[str] = ["http://localhost"]
    postgres_user: str = "dvt-user"
    postgres_db: str = "DVT"
    postgres_password: str = ""
    valkey_password: str = ""
    valkey_db: str = "0"
    grpc_token: str = ""
    fernet_key: str = ""
    ai_mcp_enabled: bool = False
    ai_mcp_internal_secret: str = ""
    external_port: str = "80"
    task_workers_count: int = Field(default=1, ge=1, le=64)


class UpdateRequest(BaseModel):
    version: str = Field(min_length=1)
    ai_mcp_enabled: bool | None = None
    ai_mcp_internal_secret: str = ""


class UpdateResponse(BaseModel):
    success: bool = True
    message: str
    version: str
    job_id: str | None = None


class JobStepSchema(BaseModel):
    id: str
    title: str
    status: str
    detail: str


class JobStatusResponse(BaseModel):
    id: str
    kind: str
    state: str
    error: str | None
    version: str
    started_at: str
    finished_at: str | None
    steps: list[JobStepSchema]
    log: list[str]
    log_total: int


class JobSummaryResponse(BaseModel):
    id: str
    kind: str
    state: str
    version: str
    started_at: str
    finished_at: str | None


class SecretsResponse(BaseModel):
    password: str
    token: str
    fernet_key: str
