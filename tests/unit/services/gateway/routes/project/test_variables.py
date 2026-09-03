from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_get_project_variables_returns_values(
    gateway_client,
    router_prefix,
    db_session,
    test_user_project,
):
    test_user_project.variables = {
        "foo": {"type": "STRING", "value": "bar", "is_list_type": False},
        "x": {"type": "INT", "value": 123, "is_list_type": False},
    }
    db_session.add(test_user_project)
    db_session.commit()

    response = await gateway_client.get(
        f"{router_prefix}/projects/{test_user_project.id}/variables/"
    )

    assert response.status_code == 200
    payload = response.json()
    assert {item["key"] for item in payload} == {"foo", "x"}
    assert {item["type"] for item in payload} == {"STRING", "INT"}


@pytest.mark.asyncio
async def test_create_update_delete_project_variable(
    gateway_client,
    router_prefix,
    test_user_project,
):
    base_url = f"{router_prefix}/projects/{test_user_project.id}/variables/sample"

    create_resp = await gateway_client.post(
        base_url,
        json={"type": "STRING", "value": "v1", "is_list_type": False},
    )
    assert create_resp.status_code == 201
    assert create_resp.json() == {
        "key": "sample",
        "type": "STRING",
        "value": "v1",
        "is_list_type": False,
    }

    update_resp = await gateway_client.put(
        base_url,
        json={"type": "STRING", "value": "v2", "is_list_type": False},
    )
    assert update_resp.status_code == 200
    assert update_resp.json() == {
        "key": "sample",
        "type": "STRING",
        "value": "v2",
        "is_list_type": False,
    }

    get_resp = await gateway_client.get(base_url)
    assert get_resp.status_code == 200
    assert get_resp.json() == {
        "key": "sample",
        "type": "STRING",
        "value": "v2",
        "is_list_type": False,
    }

    delete_resp = await gateway_client.delete(base_url)
    assert delete_resp.status_code == 204
