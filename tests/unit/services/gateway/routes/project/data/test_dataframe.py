from __future__ import annotations

import pandas as pd
import pytest

from core.types import DataType

from services.gateway.deps.caching import get_pipeline_cache_facade
from services.gateway.routes.project.data.dataframe import _stream_csv_partitions

from src.modules.pipeline_cache import GetDataFrameEntryResult
from src.modules.pipeline_cache.domain.dataframe_cache import DataFramePartitionDescriptor


class _FakePipelineCacheFacade:
    def __init__(self, result: GetDataFrameEntryResult | None = None, error: Exception | None = None):
        self._result = result
        self._error = error

    async def get_dataframe_entry(self, **_kwargs) -> GetDataFrameEntryResult:
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


class _FakeDataStore:
    def __init__(self, payloads: dict[str, object]):
        self._payloads = payloads

    async def get(self, key: str):
        return self._payloads.get(key)


@pytest.mark.asyncio
async def test_dataframe_data_returns_paginated_payload_and_column_types(
    gateway_client,
    router_prefix,
    test_user_project,
):
    from services.gateway.main import app

    cached_df = pd.DataFrame(
        {
            "int_col": [2, 3],
            "float_col": [2.5, 3.5],
            "bool_col": [False, True],
            "str_col": pd.Series(["b", "c"], dtype="string"),
            "dt_col": pd.to_datetime(["2026-01-02", "2026-01-03"]),
        }
    )
    fake_facade = _FakePipelineCacheFacade(
        GetDataFrameEntryResult(
            dataframe=cached_df,
            total_rows=4,
            total_partitions=2,
        )
    )

    app.dependency_overrides[get_pipeline_cache_facade] = lambda: fake_facade

    try:
        response = await gateway_client.get(
            f"{router_prefix}/projects/{test_user_project.id}/dataframe/node-types",
            params={"output_name": "output", "offset": 1, "limit": 2},
        )
    finally:
        app.dependency_overrides.pop(get_pipeline_cache_facade, None)

    assert response.status_code == 200

    payload = response.json()
    assert payload["total_rows"] == 4
    assert payload["total_partitions"] == 2
    assert len(payload["values"]) == 2
    assert payload["values"][0][0] == 2
    assert payload["values"][1][0] == 3

    columns_by_name = {column["name"]: column for column in payload["columns"]}
    assert columns_by_name["int_col"]["dtype"] == DataType.INT.value
    assert columns_by_name["float_col"]["dtype"] == DataType.FLOAT.value
    assert columns_by_name["bool_col"]["dtype"] == DataType.BOOLEAN.value
    assert columns_by_name["str_col"]["dtype"] == DataType.STRING.value
    assert columns_by_name["dt_col"]["dtype"] == DataType.DATETIME.value


@pytest.mark.asyncio
async def test_dataframe_data_returns_404_when_meta_is_missing(
    gateway_client,
    router_prefix,
    test_user_project,
):
    from services.gateway.main import app

    app.dependency_overrides[get_pipeline_cache_facade] = lambda: _FakePipelineCacheFacade(
        error=RuntimeError("DataFrame metadata not found in cache")
    )

    try:
        response = await gateway_client.get(
            f"{router_prefix}/projects/{test_user_project.id}/dataframe/node-missing"
        )
    finally:
        app.dependency_overrides.pop(get_pipeline_cache_facade, None)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_stream_csv_partitions_emits_bom_and_single_header() -> None:
    index_entries = [
        DataFramePartitionDescriptor(
            part_no=0,
            cache_key="part-1",
            rows=1,
            payload_bytes=10,
        ),
        DataFramePartitionDescriptor(
            part_no=1,
            cache_key="part-2",
            rows=1,
            payload_bytes=10,
        ),
        DataFramePartitionDescriptor(
            part_no=2,
            cache_key="part-3",
            rows=1,
            payload_bytes=10,
        ),
    ]
    data_store = _FakeDataStore(
        {
            "part-1": pd.DataFrame({"name": ["alpha"], "value": [1]}),
            "part-2": pd.DataFrame({"name": ["middle"], "value": [2]}),
            "part-3": pd.DataFrame({"name": ["beta"], "value": [2]}),
        }
    )

    chunks = [chunk async for chunk in _stream_csv_partitions(index_entries, data_store)]

    assert chunks
    assert chunks[0].startswith(b"\xef\xbb\xbf")

    csv_payload = b"".join(chunks).decode("utf-8-sig")
    lines = csv_payload.strip().splitlines()

    assert lines[0] == "name,value"
    assert lines.count("name,value") == 1
    assert len(lines) == 4


@pytest.mark.asyncio
async def test_stream_csv_partitions_raises_on_missing_ready_partition() -> None:
    partition_entries = (
        DataFramePartitionDescriptor(
            part_no=0,
            cache_key="part-missing",
            rows=1,
            payload_bytes=10,
        ),
    )
    data_store = _FakeDataStore({})

    with pytest.raises(RuntimeError, match="missing partition 0"):
        _ = [
            chunk
            async for chunk in _stream_csv_partitions(partition_entries, data_store)
        ]
