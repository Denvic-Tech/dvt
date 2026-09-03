from collections.abc import Mapping

from .generated.async_resources import (
    AsyncAdminResource,
    AsyncAppSettingsResource,
    AsyncConfigResource,
    AsyncDbConnectionsResource,
    AsyncExceptionsResource,
    AsyncExtensionsResource,
    AsyncLogsResource,
    AsyncMetricsResource,
    AsyncNodesResource,
    AsyncOrganizationsResource,
    AsyncProjectsResource,
    AsyncPublicResource,
    AsyncPytestMonResource,
    AsyncQueueResource,
    AsyncQueueTopicsResource,
    AsyncSetupResource,
    AsyncStorageResource,
    AsyncStoreResource,
    AsyncSystemResource,
    AsyncUserResource,
    AsyncUtilsResource,
)
from .manual_resources import AsyncAuthResource
from .resources.base import AsyncResourceInitializerMixin
from .transport import DVTAsyncTransport


class DVTClient(AsyncResourceInitializerMixin):
    auth: AsyncAuthResource
    admin: AsyncAdminResource
    app_settings: AsyncAppSettingsResource
    config: AsyncConfigResource
    db_connections: AsyncDbConnectionsResource
    exceptions: AsyncExceptionsResource
    extensions: AsyncExtensionsResource
    logs: AsyncLogsResource
    metrics: AsyncMetricsResource
    nodes: AsyncNodesResource
    organizations: AsyncOrganizationsResource
    projects: AsyncProjectsResource
    public: AsyncPublicResource
    pytest_mon: AsyncPytestMonResource
    queue: AsyncQueueResource
    queue_topics: AsyncQueueTopicsResource
    setup: AsyncSetupResource
    storage: AsyncStorageResource
    store: AsyncStoreResource
    system: AsyncSystemResource
    user: AsyncUserResource
    utils: AsyncUtilsResource

    def __init__(
        self,
        *,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
        access_token: str | None = None,
        api_token: str | None = None,
        timeout: float = 30.0,
        default_headers: Mapping[str, str] | None = None,
    ):
        self._transport = DVTAsyncTransport(
            base_url=base_url,
            username=username,
            password=password,
            access_token=access_token,
            api_token=api_token,
            timeout=timeout,
            default_headers=default_headers,
        )
        self._init_resources(self._transport)

    async def sign_in(
        self,
        *,
        username: str | None = None,
        password: str | None = None,
    ):
        return await self._transport.sign_in(username=username, password=password)

    async def aclose(self) -> None:
        await self._transport.aclose()

    async def __aenter__(self) -> "DVTClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()
