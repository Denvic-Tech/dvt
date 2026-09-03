from pathlib import Path

import pytest

from src.modules.node_documentation.domain.entities import PublishedNodeDocumentation
from src.modules.node_documentation.domain.exceptions import (
    NodeDocumentationNotFound,
    UnknownNode,
)
from src.modules.node_documentation.flow.use_cases import GetNodeDocumentation
from src.modules.node_documentation.infra.repositories import (
    FileSystemNodeDocumentationRepository,
)


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
        locale="en",
        content="# Join",
    )
    use_case = GetNodeDocumentation(
        repository=_RepositoryStub({("DataFrameJoin", "en"): documentation}),
        registry=_NodeRegistryStub({"DataFrameJoin"}),
    )

    result = await use_case.execute(node_name="DataFrameJoin", locale="en")

    assert result == documentation


@pytest.mark.asyncio
async def test_get_node_documentation_falls_back_to_ru() -> None:
    documentation = PublishedNodeDocumentation(
        node_name="DataFrameJoin",
        locale="ru",
        content="# Объединение",
    )
    use_case = GetNodeDocumentation(
        repository=_RepositoryStub({("DataFrameJoin", "ru"): documentation}),
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
        registry=_NodeRegistryStub({"DataFrameJoin"}),
    )

    with pytest.raises(NodeDocumentationNotFound):
        await use_case.execute(node_name="DataFrameJoin", locale="en")


@pytest.mark.asyncio
async def test_filesystem_repository_reads_markdown(tmp_path: Path) -> None:
    root_dir = tmp_path / "docs" / "nodes"
    node_dir = root_dir / "DataFrameJoin"
    node_dir.mkdir(parents=True)
    (node_dir / "ru.md").write_text("# Join\n", encoding="utf-8")

    repository = FileSystemNodeDocumentationRepository(root_dir=root_dir)

    result = await repository.get(node_name="DataFrameJoin", locale="ru")

    assert result == PublishedNodeDocumentation(
        node_name="DataFrameJoin",
        locale="ru",
        content="# Join\n",
    )
    assert repository.get_documented_node_names() == frozenset({"DataFrameJoin"})


@pytest.mark.asyncio
async def test_filesystem_repository_returns_none_for_missing_file(tmp_path: Path) -> None:
    repository = FileSystemNodeDocumentationRepository(
        root_dir=tmp_path / "docs" / "nodes"
    )

    result = await repository.get(node_name="DataFrameJoin", locale="en")

    assert result is None
    assert repository.get_documented_node_names() == frozenset()


@pytest.mark.asyncio
async def test_filesystem_repository_keeps_preloaded_content_until_recreated(
    tmp_path: Path,
) -> None:
    root_dir = tmp_path / "docs" / "nodes"
    node_dir = root_dir / "DataFrameJoin"
    node_dir.mkdir(parents=True)
    documentation_path = node_dir / "ru.md"
    documentation_path.write_text("# Version 1\n", encoding="utf-8")

    repository = FileSystemNodeDocumentationRepository(root_dir=root_dir)
    documentation_path.write_text("# Version 2\n", encoding="utf-8")

    result = await repository.get(node_name="DataFrameJoin", locale="ru")

    assert result == PublishedNodeDocumentation(
        node_name="DataFrameJoin",
        locale="ru",
        content="# Version 1\n",
    )


@pytest.mark.asyncio
async def test_filesystem_repository_ignores_unsupported_locales(tmp_path: Path) -> None:
    root_dir = tmp_path / "docs" / "nodes"
    node_dir = root_dir / "DataFrameJoin"
    node_dir.mkdir(parents=True)
    (node_dir / "de.md").write_text("# Deutsch\n", encoding="utf-8")

    repository = FileSystemNodeDocumentationRepository(root_dir=root_dir)

    result = await repository.get(node_name="DataFrameJoin", locale="de")

    assert result is None
    assert repository.get_documented_node_names() == frozenset()
