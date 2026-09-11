from typing import Protocol

from src.modules.extension_management.domain.entities import Extension


class ExtensionRepository(Protocol):
    async def list(self) -> list[Extension]: ...

    async def get(self, name: str) -> Extension | None: ...


__all__ = ["ExtensionRepository"]
