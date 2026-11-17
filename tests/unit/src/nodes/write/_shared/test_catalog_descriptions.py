from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.nodes.write._shared import catalog_descriptions
from src.nodes.write._shared.catalog_descriptions import (
    load_catalog_descriptions,
    map_descriptions_to_targets,
)


def test_map_descriptions_to_targets_follows_mapping_and_drops_blank_texts():
    mapped = map_descriptions_to_targets(
        {"id": " Идентификатор ", "amount": "Сумма", "note": "  ", "gone": "x"},
        {"id": "client_id", "amount": "amount"},
    )

    assert mapped == {"client_id": "Идентификатор", "amount": "Сумма", "gone": "x"}
    assert map_descriptions_to_targets({}, None) == {}


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


@pytest.mark.asyncio
async def test_load_catalog_descriptions_uses_the_catalog_facade(monkeypatch):
    import src.db
    from src.modules import data_catalog

    resolve = AsyncMock(return_value={"id": "Идентификатор", "amount": "Сумма"})
    monkeypatch.setattr(src.db, "AsyncSessionLocal", _Session)
    monkeypatch.setattr(data_catalog, "resolve_port_descriptions", resolve, raising=False)
    monkeypatch.setattr(
        catalog_descriptions, "config", SimpleNamespace(DATA_CATALOG=SimpleNamespace(WORKER_OBSERVATION_ENABLED=True)), raising=False
    )

    result = await load_catalog_descriptions(project_id="p1", node_id="w", port="df")

    assert result == {"id": "Идентификатор", "amount": "Сумма"}
    kwargs = resolve.await_args.kwargs
    assert (kwargs["project_id"], kwargs["node_id"], kwargs["port"]) == ("p1", "w", "df")


@pytest.mark.asyncio
async def test_load_catalog_descriptions_swallows_failures_and_respects_the_flag(monkeypatch):
    import src.db
    from src.modules import data_catalog

    monkeypatch.setattr(src.db, "AsyncSessionLocal", _Session)
    monkeypatch.setattr(
        data_catalog, "resolve_port_descriptions", AsyncMock(side_effect=RuntimeError("catalog down")), raising=False
    )
    assert await load_catalog_descriptions(project_id="p1", node_id="w") == {}

    import config

    monkeypatch.setattr(config.DATA_CATALOG, "WORKER_OBSERVATION_ENABLED", False)
    untouched = AsyncMock(return_value={"id": "x"})
    monkeypatch.setattr(data_catalog, "resolve_port_descriptions", untouched, raising=False)
    assert await load_catalog_descriptions(project_id="p1", node_id="w") == {}
    untouched.assert_not_awaited()
