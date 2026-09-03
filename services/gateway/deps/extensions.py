from src.clients.denvic_extensions_distributor import DenvicExtensionsDistributor
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.managers.extension_manager import ExtensionManager

import config


async def get_extension_manager(
    session: AsyncSessionDepends,
) -> ExtensionManager:
    return ExtensionManager(
        session,
        distributor_client=DenvicExtensionsDistributor(config.EXTENSIONS.DISTRIBUTOR_URL),
        gateway_runtime=True,
    )
