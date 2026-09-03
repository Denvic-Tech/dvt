from pathlib import Path

import config
from src.logger import logger

from ...domain.entities import PublishedNodeDocumentation, SUPPORTED_LOCALES
from ...domain.repositories import NodeDocumentationRepository


class FileSystemNodeDocumentationRepository(NodeDocumentationRepository):
    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = Path(root_dir or config.PROJECT.NODE_DOCUMENTATION_DIR)
        self._items = self._load_items()
        self._documented_node_names = frozenset(
            node_name
            for node_name, _locale in self._items
        )

    async def get(
        self,
        *,
        node_name: str,
        locale: str,
    ) -> PublishedNodeDocumentation | None:
        return self._items.get((node_name, locale))

    def get_documented_node_names(self) -> frozenset[str]:
        return self._documented_node_names

    def has_any(self, node_name: str) -> bool:
        return node_name in self._documented_node_names

    def _load_items(self) -> dict[tuple[str, str], PublishedNodeDocumentation]:
        if not self.root_dir.exists():
            logger.debug(
                "Node documentation directory does not exist: {}",
                self.root_dir,
            )
            return {}

        if not self.root_dir.is_dir():
            logger.warning(
                "Node documentation path is not a directory: {}",
                self.root_dir,
            )
            return {}

        items: dict[tuple[str, str], PublishedNodeDocumentation] = {}
        for node_dir in sorted(self.root_dir.iterdir()):
            if not node_dir.is_dir():
                continue

            for documentation_path in sorted(node_dir.glob("*.md")):
                locale = documentation_path.stem.strip().lower()
                if locale not in SUPPORTED_LOCALES:
                    logger.warning(
                        "Skip node documentation with unsupported locale '{}' at {}",
                        locale,
                        documentation_path,
                    )
                    continue

                try:
                    content = documentation_path.read_text(encoding="utf-8")
                except OSError:
                    logger.exception(
                        "Failed to read node documentation from {}",
                        documentation_path,
                    )
                    continue

                items[(node_dir.name, locale)] = PublishedNodeDocumentation(
                    node_name=node_dir.name,
                    locale=locale,
                    content=content,
                )

        return items
