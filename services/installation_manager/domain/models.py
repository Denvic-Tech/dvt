"""Доменные модели: конфигурации install/update и задача (job) с шагами."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class JobKind(str, Enum):
    INSTALL = "install"
    UPDATE = "update"


class JobState(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    FAILED = "failed"


@dataclass
class JobStep:
    id: str
    title: str
    status: StepStatus = StepStatus.PENDING
    detail: str = ""


@dataclass
class InstallConfig:
    """Параметры полной установки DVT."""

    version: str = "latest"
    public_urls: list[str] = field(default_factory=lambda: ["http://localhost"])
    postgres_user: str = "dvt-user"
    postgres_db: str = "DVT"
    postgres_password: str = ""
    valkey_password: str = ""
    valkey_db: str = "0"
    grpc_token: str = ""
    fernet_key: str = ""
    jwt_access_token_secret_key: str = ""
    jwt_refresh_token_secret_key: str = ""
    jwt_onetime_token_secret_key: str = ""
    jwt_api_token_secret_key: str = ""
    code_hash_salt: str = ""
    ai_mcp_enabled: bool = False
    ai_mcp_internal_secret: str = ""
    external_port: str = "80"
    task_workers_count: int = 1
    project_name: str = "dvt"
    lib_dir_host: str = "/var/lib/dvt"

    @property
    def public_url(self) -> str:
        return ";".join(u.strip() for u in self.public_urls if u.strip())

    @property
    def cookie_secure(self) -> str:
        return "true" if "https://" in self.public_url.lower() else "false"


@dataclass
class UpdateConfig:
    """Параметры обновления DVT."""

    version: str
    ai_mcp_enabled: bool | None = None
    ai_mcp_internal_secret: str = ""


class Job:
    """Потокобезопасное состояние выполняющейся установки/обновления."""

    def __init__(self, kind: JobKind, steps: list[tuple[str, str]]):
        self.id = str(uuid.uuid4())
        self.kind = kind
        self.state = JobState.RUNNING
        self.error: str | None = None
        self.version: str = ""
        self.started_at = datetime.now(timezone.utc)
        self.finished_at: datetime | None = None
        self.steps = [JobStep(id=s, title=t) for s, t in steps]
        self._log: list[str] = []
        self._lock = threading.Lock()

    def log(self, line: str) -> None:
        with self._lock:
            for part in line.splitlines() or [""]:
                self._log.append(part)

    def set_step(self, step_id: str, status: StepStatus, detail: str = "") -> None:
        with self._lock:
            for step in self.steps:
                if step.id == step_id:
                    step.status = status
                    if detail:
                        step.detail = detail

    def finish(self, state: JobState, error: str | None = None) -> None:
        with self._lock:
            self.state = state
            self.error = error
            self.finished_at = datetime.now(timezone.utc)

    def snapshot(self, log_offset: int = 0) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "kind": self.kind.value,
                "state": self.state.value,
                "error": self.error,
                "version": self.version,
                "started_at": self.started_at.isoformat(),
                "finished_at": self.finished_at.isoformat() if self.finished_at else None,
                "steps": [
                    {"id": s.id, "title": s.title, "status": s.status.value, "detail": s.detail}
                    for s in self.steps
                ],
                "log": self._log[log_offset:],
                "log_total": len(self._log),
            }

    def summary(self) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "kind": self.kind.value,
                "state": self.state.value,
                "version": self.version,
                "started_at": self.started_at.isoformat(),
                "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            }
