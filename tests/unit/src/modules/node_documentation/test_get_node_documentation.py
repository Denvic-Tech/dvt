import pytest

from src.modules.node_documentation.domain.entities import PublishedNodeDocumentation
from src.modules.node_documentation.domain.exceptions import (
    NodeDocumentationNotFound,
    UnknownNode,
)
from src.modules.node_documentation.flow.use_cases import GetNodeDocumentation
from src.modules.node_documentation.infra.repositories import NodePackageDocumentationRepository
from src.node_dsl import get_all_node_packages


class _NodeRegistryStub:
    def __init__(self, available_nodes: set[str]) -> None:
        self.available_nodes = available_nodes

    def contains(self, node_name: str) -> bool:
        return node_name in self.available_nodes


class _RepositoryStub:
    def __init__(self, items: dict[tuple[str, str], PublishedNodeDocumentation]) -> None:
        self.items = items

    async def get(
        self,
        *,
        node_name: str,
        locale: str,
    ) -> PublishedNodeDocumentation | None:
        return self.items.get((node_name, locale))


@pytest.mark.asyncio
async def test_get_node_documentation_returns_exact_locale() -> None:
    documentation = PublishedNodeDocumentation(
        node_name="DataFrameJoin",
        locale="ru",
        content="# Объединение",
    )
    use_case = GetNodeDocumentation(
        repository=_RepositoryStub({("DataFrameJoin", "ru"): documentation}),
        registry=_NodeRegistryStub({"DataFrameJoin"}),
    )

    result = await use_case.execute(node_name="DataFrameJoin", locale="ru")

    assert result == documentation


@pytest.mark.asyncio
async def test_get_node_documentation_falls_back_from_ru_to_english() -> None:
    documentation = PublishedNodeDocumentation(
        node_name="DataFrameJoin",
        locale="en",
        content="# Join",
    )
    use_case = GetNodeDocumentation(
        repository=_RepositoryStub({("DataFrameJoin", "en"): documentation}),
        registry=_NodeRegistryStub({"DataFrameJoin"}),
    )

    result = await use_case.execute(node_name="DataFrameJoin", locale="ru")

    assert result == documentation


@pytest.mark.asyncio
async def test_get_node_documentation_unsupported_locale_uses_english() -> None:
    documentation = PublishedNodeDocumentation(
        node_name="DataFrameJoin",
        locale="en",
        content="# Join",
    )
    use_case = GetNodeDocumentation(
        repository=_RepositoryStub({("DataFrameJoin", "en"): documentation}),
        registry=_NodeRegistryStub({"DataFrameJoin"}),
    )

    result = await use_case.execute(node_name="DataFrameJoin", locale="de")

    assert result == documentation


@pytest.mark.asyncio
async def test_get_node_documentation_raises_for_unknown_node() -> None:
    use_case = GetNodeDocumentation(
        repository=_RepositoryStub({}),
        registry=_NodeRegistryStub(set()),
    )

    with pytest.raises(UnknownNode):
        await use_case.execute(node_name="MissingNode", locale="ru")


@pytest.mark.asyncio
async def test_get_node_documentation_raises_when_documentation_missing() -> None:
    use_case = GetNodeDocumentation(
        repository=_RepositoryStub({}),
        registry=_NodeRegistryStub({"LoadCSV"}),
    )

    with pytest.raises(NodeDocumentationNotFound):
        await use_case.execute(node_name="LoadCSV", locale="en")


@pytest.mark.asyncio
async def test_package_repository_reads_colocated_readmes() -> None:
    repository = NodePackageDocumentationRepository()

    english = await repository.get(node_name="DataFrameJoin", locale="en")
    russian = await repository.get(node_name="DataFrameJoin", locale="ru")

    assert english is not None
    assert english.locale == "en"
    assert english.content.startswith("# DataFrame Join")
    assert russian is not None
    assert russian.locale == "ru"
    assert russian.content.startswith("# Объединение DataFrame")
    assert "DataFrameJoin" in repository.get_documented_node_names()


@pytest.mark.asyncio
async def test_package_repository_returns_none_for_missing_documentation() -> None:
    repository = NodePackageDocumentationRepository()

    result = await repository.get(node_name="LoadCSV", locale="en")

    assert result is None
    assert repository.has_any("LoadCSV") is False


def test_package_repository_reads_current_catalog_without_stale_snapshot(monkeypatch) -> None:
    catalog = get_all_node_packages()
    repository = NodePackageDocumentationRepository(package_catalog=lambda: catalog)

    assert repository.has_any("DataFrameJoin") is True
    catalog.pop("DataFrameJoin")
    assert repository.has_any("DataFrameJoin") is False
