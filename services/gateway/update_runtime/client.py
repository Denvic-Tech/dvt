from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx


class InstallationManagerUnavailable(RuntimeError):
    pass


class InstallationManagerNoJob(RuntimeError):
    pass


class InstallationManagerHTTPError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class UpdateJobSummary:
    id: str
    kind: str
    state: str
    version: str
    started_at: datetime
    finished_at: datetime | None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "UpdateJobSummary":
        return cls(
            id=str(payload["id"]),
            kind=str(payload["kind"]),
            state=str(payload["state"]),
            version=str(payload.get("version", "")),
            started_at=datetime.fromisoformat(str(payload["started_at"])),
            finished_at=(
                datetime.fromisoformat(str(payload["finished_at"]))
                if payload.get("finished_at")
                else None
            ),
        )


class InstallationManagerClient:
    def __init__(
        self,
        base_url: str,
        request_timeout_sec: float,
        summary_timeout_sec: float | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._request_timeout_sec = request_timeout_sec
        self._summary_timeout_sec = summary_timeout_sec or request_timeout_sec
        self._client = self._new_client()

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._request_timeout_sec,
        )

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self._client.is_closed:
            self._client = self._new_client()
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise InstallationManagerUnavailable("update-service unreachable") from exc

        if response.status_code == 404 and path == "/api/jobs/current/summary":
            raise InstallationManagerNoJob from None
        if response.is_error:
            detail = response.text.strip() or "update-service failed"
            raise InstallationManagerHTTPError(response.status_code, detail)
        return response

    async def get_current_job_summary(self) -> UpdateJobSummary:
        response = await self.request(
            "GET",
            "/api/jobs/current/summary",
            timeout=self._summary_timeout_sec,
        )
        return UpdateJobSummary.from_payload(response.json())

    async def close(self) -> None:
        await self._client.aclose()
