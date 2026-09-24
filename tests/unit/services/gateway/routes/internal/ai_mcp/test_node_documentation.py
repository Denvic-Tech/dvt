from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.gateway.deps.node_documentation import reset_node_documentation_repository_cache
from services.gateway.routes.internal.ai_mcp import context, router
from services.gateway.routes.internal.ai_mcp.errors import AIMCPHTTPError
from services.gateway.routes.internal.ai_mcp.schemas import ToolCallSchema
from src.modules.node_documentation.infra.repositories import node_documentation as repository_module


@pytest.fixture(autouse=True)
def _builtin_catalog(monkeypatch):
    reset_node_documentation_repository_cache()
    monkeypatch.setattr(context, "_ready_extensions", AsyncMock(return_value=set()))
    yield
    reset_node_documentation_repository_cache()


async def _call(tool, **arguments):
    principal = SimpleNamespace(
        user=SimpleNamespace(id="user-id"), token=SimpleNamespace(id="token-id"),
    )
    response = await router.call_tool(
        tool, ToolCallSchema(arguments=arguments), AsyncMock(), principal, None, None,
    )
    return response.result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("locale", "heading"),
    [("en", "# DataFrame Join"), ("ru", "# Объединение DataFrame"), ("de", "# DataFrame Join")],
)
async def test_definition_delivers_package_documentation(locale, heading):
    result = await _call("get_node_definition", node_name="DataFrameJoin", locale=locale)

    assert result["name"] == "DataFrameJoin"
    assert result["documentation"].startswith(heading)
    assert result["documentation_available"] is True
    assert "left_on" in result["input_definitions"]
    assert "output" in result["output_definitions"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("locale", "query"), [("en", "cardinality"), ("ru", "кратности")])
async def test_search_finds_readme_text_and_keeps_results_compact(locale, query, monkeypatch, tmp_path):
    # Use controlled prose absent from schema metadata to prove README search itself.
    (tmp_path / "README.md").write_text("# Fixture\nUnique cardinality example", encoding="utf-8")
    (tmp_path / "README.ru.md").write_text("# Пример\nОписание кратности", encoding="utf-8")
    monkeypatch.setattr(repository_module, "resources", SimpleNamespace(files=lambda _: tmp_path))
    definition = context.get_definition(node_name="DataFrameJoin", lang=locale)
    monkeypatch.setattr(
        context, "_available_definitions", AsyncMock(return_value={"DataFrameJoin": definition}),
    )
    metadata = " ".join(
        [definition.name, definition.display_name, definition.description, *definition.tags],
    ).lower()
    assert query not in metadata

    result = await _call("search_nodes", query=query, locale=locale)

    assert [item["name"] for item in result["items"]] == ["DataFrameJoin"]
    assert set(result["items"][0]) == {
        "name", "display_name", "description", "category", "tags", "type",
        "input_types", "output_types", "extension_name",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(("locale", "query"), [("en", "Cartesian"), ("ru", "декартово")])
async def test_search_finds_published_join_readme(locale, query):
    result = await _call("search_nodes", query=query, locale=locale)

    assert "DataFrameJoin" in {item["name"] for item in result["items"]}
    assert all("documentation" not in item for item in result["items"])


@pytest.mark.asyncio
async def test_missing_translation_uses_english_for_definition_and_search(monkeypatch, tmp_path):
    content = "# Fixture\nenglishfallbackneedle"
    (tmp_path / "README.md").write_text(content, encoding="utf-8")
    monkeypatch.setattr(repository_module, "resources", SimpleNamespace(files=lambda _: tmp_path))

    definition = await _call("get_node_definition", node_name="LoadCSV", locale="ru")
    search = await _call("search_nodes", query="englishfallbackneedle", locale="ru", limit=200)

    assert definition["documentation"] == content
    assert definition["documentation_available"] is True
    assert "LoadCSV" in {item["name"] for item in search["items"]}


@pytest.mark.asyncio
async def test_missing_readme_keeps_definition_available(monkeypatch, tmp_path):
    monkeypatch.setattr(repository_module, "resources", SimpleNamespace(files=lambda _: tmp_path))

    result = await _call("get_node_definition", node_name="LoadCSV")

    assert result["name"] == "LoadCSV"
    assert result["documentation"] is None
    assert result["documentation_available"] is False
    assert result["input_definitions"]


@pytest.mark.asyncio
@pytest.mark.parametrize("node_name", ["ReadQueueTopic", "UnknownNode"])
async def test_unavailable_node_does_not_expose_documentation(node_name, monkeypatch):
    read_documentation = AsyncMock()
    monkeypatch.setattr(context, "_node_documentation", read_documentation)

    with pytest.raises(AIMCPHTTPError) as raised:
        await _call("get_node_definition", node_name=node_name)

    assert raised.value.status_code == 404
    assert raised.value.detail["code"] == "NODE_NOT_AVAILABLE"
    read_documentation.assert_not_awaited()


@pytest.mark.asyncio
async def test_definition_delivers_agent_guidance_without_localizing_it():
    english = await _call("get_node_definition", node_name="ReadTableFromDBV3", locale="en")
    russian = await _call("get_node_definition", node_name="ReadTableFromDBV3", locale="ru")
    english_key = english["input_definitions"]["partition_col"]
    russian_key = russian["input_definitions"]["partition_col"]

    assert english_key["description"] != russian_key["description"]
    assert english_key["agent_description"] == russian_key["agent_description"]
    assert "nulls" in english_key["agent_description"]
    assert "skew" in english_key["agent_description"]
    assert english["documentation"]
    # Shared base fields carry the same guidance through the MCP facade in either locale.
    signal_guidance = english["input_definitions"]["signal_in"]["agent_description"]
    assert signal_guidance
    assert signal_guidance == russian["input_definitions"]["signal_in"]["agent_description"]
