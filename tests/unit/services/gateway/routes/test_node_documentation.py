import pytest

from services.gateway.deps.node_documentation import reset_node_documentation_repository_cache


@pytest.fixture(autouse=True)
def _reset_node_documentation_cache() -> None:
    reset_node_documentation_repository_cache()
    yield
    reset_node_documentation_repository_cache()


@pytest.mark.asyncio
async def test_get_node_documentation_route_returns_exact_ru_locale(
    gateway_client,
    router_prefix,
) -> None:
    response = await gateway_client.get(
        f"{router_prefix}/nodes/DataFrameJoin/documentation",
        headers={"X-Language": "ru"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["node_name"] == "DataFrameJoin"
    assert response.json()["locale"] == "ru"
    assert response.json()["content"].startswith("# Объединение DataFrame")


@pytest.mark.asyncio
async def test_get_node_documentation_route_returns_english_locale(
    gateway_client,
    router_prefix,
) -> None:
    response = await gateway_client.get(
        f"{router_prefix}/nodes/DataFrameJoin/documentation",
        headers={"X-Language": "en"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["locale"] == "en"
    assert response.json()["content"].startswith("# DataFrame Join")


@pytest.mark.asyncio
async def test_get_node_documentation_route_unsupported_locale_falls_back_to_english(
    gateway_client,
    router_prefix,
) -> None:
    response = await gateway_client.get(
        f"{router_prefix}/nodes/DataFrameJoin/documentation",
        headers={"X-Language": "de"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["locale"] == "en"
    assert response.json()["content"].startswith("# DataFrame Join")


@pytest.mark.asyncio
async def test_get_node_documentation_route_returns_404_for_unknown_node(
    gateway_client,
    router_prefix,
) -> None:
    response = await gateway_client.get(
        f"{router_prefix}/nodes/UnknownNode/documentation"
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_node_documentation_route_returns_404_for_missing_documentation(
    gateway_client,
    router_prefix,
) -> None:
    response = await gateway_client.get(
        f"{router_prefix}/nodes/LoadCSV/documentation"
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_node_definitions_route_marks_documentation_availability(
    gateway_client,
    router_prefix,
) -> None:
    response = await gateway_client.get(f"{router_prefix}/nodes/")

    assert response.status_code == 200, response.text
    definitions = response.json()
    assert definitions["DataFrameJoin"]["documentation_available"] is True
    assert definitions["LoadCSV"]["documentation_available"] is False


@pytest.mark.asyncio
async def test_get_node_definition_route_marks_documentation_availability(
    gateway_client,
    router_prefix,
) -> None:
    response = await gateway_client.get(f"{router_prefix}/nodes/DataFrameJoin")

    assert response.status_code == 200, response.text
    assert response.json()["documentation_available"] is True


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
