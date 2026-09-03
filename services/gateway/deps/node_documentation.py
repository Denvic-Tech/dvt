from functools import lru_cache

from src.modules.node_documentation.infra import FileSystemNodeDocumentationRepository


@lru_cache(maxsize=1)
def get_node_documentation_repository() -> FileSystemNodeDocumentationRepository:
    return FileSystemNodeDocumentationRepository()


def preload_node_documentation_repository() -> FileSystemNodeDocumentationRepository:
    return get_node_documentation_repository()


def reset_node_documentation_repository_cache() -> None:
    get_node_documentation_repository.cache_clear()
