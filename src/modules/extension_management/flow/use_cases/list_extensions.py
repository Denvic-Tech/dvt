from src.modules.extension_management.domain.entities import Extension
from src.modules.extension_management.domain.repositories.extension_management import (
    ExtensionRepository,
)


class ListExtensionsUseCase:
    def __init__(self, repository: ExtensionRepository) -> None:
        self._repository = repository

    async def execute(self) -> list[Extension]:
        return await self._repository.list()
