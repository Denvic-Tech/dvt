from collections.abc import Mapping

from .generated.sync_resources import (
    SyncAdminResource,
    SyncAppSettingsResource,
    SyncConfigResource,
    SyncDbConnectionsResource,
    SyncExceptionsResource,
    SyncExtensionsResource,
    SyncLogsResource,
    SyncMetricsResource,
    SyncNodesResource,
    SyncOrganizationsResource,
    SyncProjectsResource,
    SyncPublicResource,
    SyncPytestMonResource,
    SyncQueueResource,
    SyncQueueTopicsResource,
    SyncSetupResource,
    SyncStorageResource,
    SyncStoreResource,
    SyncSystemResource,
    SyncUserResource,
    SyncUtilsResource,
)
from .manual_resources import SyncAuthResource
from .resources.base import SyncResourceInitializerMixin
from .transport import DVTSyncTransport


class DVTSyncClient(SyncResourceInitializerMixin):
    auth: SyncAuthResource
    admin: SyncAdminResource
    app_settings: SyncAppSettingsResource
    config: SyncConfigResource
    db_connections: SyncDbConnectionsResource
    exceptions: SyncExceptionsResource
    extensions: SyncExtensionsResource
    logs: SyncLogsResource
    metrics: SyncMetricsResource
    nodes: SyncNodesResource
    organizations: SyncOrganizationsResource
    projects: SyncProjectsResource
    public: SyncPublicResource
    pytest_mon: SyncPytestMonResource
    queue: SyncQueueResource
    queue_topics: SyncQueueTopicsResource
    setup: SyncSetupResource
    storage: SyncStorageResource
    store: SyncStoreResource
    system: SyncSystemResource
    user: SyncUserResource
    utils: SyncUtilsResource

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
        self._transport = DVTSyncTransport(
            base_url=base_url,
            username=username,
            password=password,
            access_token=access_token,
            api_token=api_token,
            timeout=timeout,
            default_headers=default_headers,
        )
        self._init_resources(self._transport)

    def sign_in(
        self,
        *,
        username: str | None = None,
        password: str | None = None,
    ):
        return self._transport.sign_in(username=username, password=password)

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> "DVTSyncClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
