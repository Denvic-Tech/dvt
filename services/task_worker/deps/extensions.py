from fastapi import Depends

import config
from src.clients.denvic_extensions_distributor import DenvicExtensionsDistributor
from src.db import get_async_session
from src.managers.extension_manager import ExtensionManager


async def get_extension_manager(session=Depends(get_async_session)) -> ExtensionManager:
    return ExtensionManager(session, distributor_client=DenvicExtensionsDistributor(config.EXTENSIONS.DISTRIBUTOR_URL))