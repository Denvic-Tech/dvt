from pathlib import Path

import pytest

import config
from services.gateway.deps.node_documentation import (
    reset_node_documentation_repository_cache,
)


def _write_documentation(
    root_dir: Path,
    *,
    node_name: str,
    locale: str,
    content: str,
) -> None:
    node_dir = root_dir / node_name
    node_dir.mkdir(parents=True, exist_ok=True)
    (node_dir / f"{locale}.md").write_text(content, encoding="utf-8")


@pytest.fixture(autouse=True)
def _reset_node_documentation_cache() -> None:
    reset_node_documentation_repository_cache()
    yield
    reset_node_documentation_repository_cache()


@pytest.mark.asyncio
async def test_get_node_documentation_route_returns_exact_locale(
    gateway_client,
    router_prefix,
    monkeypatch,
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "docs" / "nodes"
    _write_documentation(
        docs_dir,
        node_name="DataFrameJoin",
        locale="en",
        content="# Join guide",
    )
    monkeypatch.setattr(config.PROJECT, "NODE_DOCUMENTATION_DIR", docs_dir)
    reset_node_documentation_repository_cache()

    response = await gateway_client.get(
        f"{router_prefix}/nodes/DataFrameJoin/documentation",
        headers={"X-Language": "en"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "node_name": "DataFrameJoin",
        "locale": "en",
        "content": "# Join guide",
    }


@pytest.mark.asyncio
async def test_get_node_documentation_route_falls_back_to_ru(
    gateway_client,
    router_prefix,
    monkeypatch,
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "docs" / "nodes"
    _write_documentation(
        docs_dir,
        node_name="DataFrameJoin",
        locale="ru",
        content="# Руководство",
    )
    monkeypatch.setattr(config.PROJECT, "NODE_DOCUMENTATION_DIR", docs_dir)
    reset_node_documentation_repository_cache()

    response = await gateway_client.get(
        f"{router_prefix}/nodes/DataFrameJoin/documentation",
        headers={"X-Language": "de"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["locale"] == "ru"
    assert response.json()["content"] == "# Руководство"


@pytest.mark.asyncio
async def test_get_node_documentation_route_returns_404_for_unknown_node(
    gateway_client,
    router_prefix,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        config.PROJECT,
        "NODE_DOCUMENTATION_DIR",
        tmp_path / "docs" / "nodes",
    )
    reset_node_documentation_repository_cache()

    response = await gateway_client.get(
        f"{router_prefix}/nodes/UnknownNode/documentation"
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_node_documentation_route_returns_404_for_missing_documentation(
    gateway_client,
    router_prefix,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        config.PROJECT,
        "NODE_DOCUMENTATION_DIR",
        tmp_path / "docs" / "nodes",
    )
    reset_node_documentation_repository_cache()

    response = await gateway_client.get(
        f"{router_prefix}/nodes/DataFrameJoin/documentation"
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_node_definitions_route_marks_documentation_availability(
    gateway_client,
    router_prefix,
    monkeypatch,
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "docs" / "nodes"
    _write_documentation(
        docs_dir,
        node_name="DataFrameJoin",
        locale="ru",
        content="# Join guide",
    )
    monkeypatch.setattr(config.PROJECT, "NODE_DOCUMENTATION_DIR", docs_dir)
    reset_node_documentation_repository_cache()

    response = await gateway_client.get(f"{router_prefix}/nodes/")

    assert response.status_code == 200, response.text
    definitions = response.json()
    assert definitions["DataFrameJoin"]["documentation_available"] is True
    assert any(
        not definition["documentation_available"]
        for node_name, definition in definitions.items()
        if node_name != "DataFrameJoin"
    )


@pytest.mark.asyncio
async def test_get_base_variable_definitions_route_returns_error_text_contract(
    gateway_client,
    router_prefix,
) -> None:
    response = await gateway_client.get(f"{router_prefix}/nodes/base-variable-definitions")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["__dvt_error_text"]["type"] == "STRING"
    assert payload["__dvt_error_text"]["required"] is False
    assert "error" in payload["__dvt_error_text"]["description"].lower()
