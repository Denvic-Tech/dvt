from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib import resources

from src.logger import logger
from src.node_dsl import get_all_node_packages
from src.node_dsl.discovery.types import NodePackageDescriptor

from ...domain.entities import PublishedNodeDocumentation
from ...domain.repositories import NodeDocumentationRepository

_LOCALE_FILENAMES = {
    "en": "README.md",
    "ru": "README.ru.md",
}


class NodePackageDocumentationRepository(NodeDocumentationRepository):
    def __init__(
        self,
        package_catalog: Callable[[], Mapping[str, NodePackageDescriptor]] | None = None,
    ) -> None:
        self._package_catalog = package_catalog or get_all_node_packages

    async def get(
        self,
        *,
        node_name: str,
        locale: str,
    ) -> PublishedNodeDocumentation | None:
        descriptor = self._package_catalog().get(node_name)
        if descriptor is None or descriptor.legacy:
            return None
        filename = _LOCALE_FILENAMES.get(locale)
        if filename is None:
            return None
        content = self._read_resource(descriptor, filename)
        if content is None:
            return None
        return PublishedNodeDocumentation(
            node_name=node_name,
            locale=locale,
            content=content,
        )

    def get_documented_node_names(self) -> frozenset[str]:
        return frozenset(
            node_name
            for node_name, descriptor in self._package_catalog().items()
            if not descriptor.legacy
            and any(
                self._resource_exists(descriptor, filename)
                for filename in _LOCALE_FILENAMES.values()
            )
        )

    def has_any(self, node_name: str) -> bool:
        descriptor = self._package_catalog().get(node_name)
        if descriptor is None or descriptor.legacy:
            return False
        return any(
            self._resource_exists(descriptor, filename)
            for filename in _LOCALE_FILENAMES.values()
        )

    @staticmethod
    def _resource_exists(descriptor: NodePackageDescriptor, filename: str) -> bool:
        try:
            return resources.files(descriptor.package_module).joinpath(filename).is_file()
        except (ModuleNotFoundError, AttributeError, OSError):
            logger.exception(
                "Failed to inspect node documentation resource '{}' in package '{}'",
                filename,
                descriptor.package_module,
            )
            return False

    @staticmethod
    def _read_resource(descriptor: NodePackageDescriptor, filename: str) -> str | None:
        try:
            resource = resources.files(descriptor.package_module).joinpath(filename)
            if not resource.is_file():
                return None
            return resource.read_text(encoding="utf-8")
        except (ModuleNotFoundError, AttributeError, OSError):
            logger.exception(
                "Failed to read node documentation resource '{}' in package '{}'",
                filename,
                descriptor.package_module,
            )
            return None
