from typing import Protocol


class DVTActor(Protocol):
    id: str
    organization_id: str
    role: str
