from __future__ import annotations

from src.modules.extension_management.flow.providers import ExtensionManagementProvider
from src.modules.extension_management.infra.gateways.extension_management import (
    ExtensionManagementGatewayAdapter,
)
from src.modules.extension_management.infra.management_service import ExtensionManager
from src.modules.extension_management.infra.repositories.extension_management import (
    SQLExtensionRepository,
)


def build_extension_management_provider(
    session,
    distributor_client,
    *,
    gateway_runtime: bool = False,
) -> ExtensionManagementProvider:
    manager = ExtensionManager(
        session,
        distributor_client=distributor_client,
        gateway_runtime=gateway_runtime,
    )
    gateway = ExtensionManagementGatewayAdapter(manager)
    repository = SQLExtensionRepository(session)
    return ExtensionManagementProvider(
        repository=repository,
        query_gateway=gateway,
        lifecycle_gateway=gateway,
        package_gateway=gateway,
        close_callback=distributor_client.aclose,
    )


__all__ = ["build_extension_management_provider"]
