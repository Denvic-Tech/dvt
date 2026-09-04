from ...domain.entities import (
    DEFAULT_FALLBACK_LOCALE,
    PublishedNodeDocumentation,
    normalize_requested_locale,
)
from ...domain.exceptions import NodeDocumentationNotFound, UnknownNode
from ...domain.gateways import NodeRegistry
from ...domain.repositories import NodeDocumentationRepository


class GetNodeDocumentation:
    def __init__(
        self,
        repository: NodeDocumentationRepository,
        registry: NodeRegistry,
    ) -> None:
        self.repository = repository
        self.registry = registry

    async def execute(
        self,
        *,
        node_name: str,
        locale: str,
    ) -> PublishedNodeDocumentation:
        if not self.registry.contains(node_name):
            raise UnknownNode(node_name)

        requested_locale = normalize_requested_locale(locale)
        documentation = await self.repository.get(
            node_name=node_name,
            locale=requested_locale,
        )
        if documentation is not None:
            return documentation

        if requested_locale != DEFAULT_FALLBACK_LOCALE:
            fallback_documentation = await self.repository.get(
                node_name=node_name,
                locale=DEFAULT_FALLBACK_LOCALE,
            )
            if fallback_documentation is not None:
                return fallback_documentation

        raise NodeDocumentationNotFound(node_name)
