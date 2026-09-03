from src.modules.file_storage.flow.connections import ResolvedS3StorageConnection
from src.modules.file_storage.flow.providers import FileStorageProvider


class _Factory:
    def __init__(self, gateway) -> None:
        self.gateway = gateway
        self.connection = None

    def build(self, connection):
        self.connection = connection
        return self.gateway


async def test_provider_resolves_gateway_for_accessible_connection() -> None:
    connection = ResolvedS3StorageConnection(client=object(), bucket="bucket", prefix="incoming")
    gateway = object()
    factory = _Factory(gateway)
    provider = FileStorageProvider(
        connection=connection,
        gateway_factory=factory,
    )

    resolved = await provider.get_gateway()

    assert resolved is gateway
    assert factory.connection is connection
