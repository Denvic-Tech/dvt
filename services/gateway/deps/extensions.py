from collections.abc import AsyncIterator

from src.clients.denvic_extensions_distributor import DenvicExtensionsDistributor
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.modules.extension_management.flow.providers import ExtensionManagementProvider
from src.runtime.extension_management import build_extension_management_provider

import config


async def get_extension_manager(
    session: AsyncSessionDepends,
) -> AsyncIterator[ExtensionManagementProvider]:
    distributor_client = DenvicExtensionsDistributor(config.EXTENSIONS.DISTRIBUTOR_URL)
    provider = build_extension_management_provider(
        session,
        distributor_client,
        gateway_runtime=True,
    )
    try:
        yield provider
    finally:
        await provider.close()
