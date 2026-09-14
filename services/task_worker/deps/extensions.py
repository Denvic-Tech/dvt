from fastapi import Depends

from src.clients.denvic_extensions_distributor import DenvicExtensionsDistributor
from src.db import get_async_session
from src.modules.extension_management.flow.providers import ExtensionManagementProvider
from src.runtime.extension_management import build_extension_management_provider

import config


async def get_extension_manager(
    session=Depends(get_async_session),
) -> ExtensionManagementProvider:
    distributor_client = DenvicExtensionsDistributor(config.EXTENSIONS.DISTRIBUTOR_URL)
    return build_extension_management_provider(session, distributor_client)