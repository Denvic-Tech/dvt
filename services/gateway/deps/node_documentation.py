from functools import lru_cache

from src.modules.node_documentation.infra import NodePackageDocumentationRepository


@lru_cache(maxsize=1)
def get_node_documentation_repository() -> NodePackageDocumentationRepository:
    return NodePackageDocumentationRepository()


def preload_node_documentation_repository() -> NodePackageDocumentationRepository:
    return get_node_documentation_repository()


def reset_node_documentation_repository_cache() -> None:
    get_node_documentation_repository.cache_clear()
