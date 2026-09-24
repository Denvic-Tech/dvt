import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", ["en", "ru"])
async def test_node_icon_contract_in_list_and_detail(gateway_client, router_prefix, locale):
    headers = {"X-Language": locale}
    response = await gateway_client.get(f"{router_prefix}/nodes/", headers=headers)
    assert response.status_code == 200, response.text
    nodes = response.json()

    for name, key in (
        ("ReadTableFromDBV3", "table-from-db"),
        ("DataFrameJoin", "join-tables"),
        ("WriteDataFrameToDBV4", "write-to-db"),
        ("ExpandJSON", "expand-json"),
        ("ExecuteSQL", "execute-sql"),
        ("Text", "text"),
        ("SaveParquet", "save-parquet"),
        ("DataFrameUnpivot", "dataframe-unpivot"),
        ("GetMockTableSchema", "get-mock-table-schema"),
    ):
        detail = await gateway_client.get(f"{router_prefix}/nodes/{name}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert nodes[name]["icon_key"] == key
        assert detail.json()["icon_key"] == key
        assert detail.json()["emoji"] == nodes[name]["emoji"]
        assert "icon_svg" not in detail.json()
        assert "icon_url" not in detail.json()
