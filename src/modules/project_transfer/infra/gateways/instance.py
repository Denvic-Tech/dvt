from __future__ import annotations

from src.modules.installation_identity.facade import get_installation_identity
from src.modules.project_transfer.domain.gateways import InstanceInfoProvider
from src.modules.project_transfer.domain.value_objects import InstanceInfo

import config


class LocalInstanceInfoProvider(InstanceInfoProvider):
    def get(self) -> InstanceInfo:
        return InstanceInfo(
            instance_id=str(get_installation_identity().instance_id),
            version=str(config.APP.VERSION),
        )
