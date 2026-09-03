from __future__ import annotations

from uuid import uuid4

import pandas as pd
import pytest

from core.types import DataType

from services.gateway.routes.project.data.dataframe import dataframe_data

from src.modules.pipeline_cache import (
    CacheNamespaces,
    CodecObjectStore,
    DumpEngineCodec,
    PipelineCacheProvider,
    PipelineCacheSettings,
    RedisBlobStore,
    RedisIndexStore,
    RedisStoreSettings,
)
from src.modules.pipeline_cache.domain.dataframe_cache import DataFrameExecutionOrder
from src.modules.pipeline_cache.flow.dataframe_execution_cache import DataFrameExecutionCache

pytestmark = [pytest.mark.asyncio, pytest.mark.docker_required]


def _build_redis_url(redis_container) -> str:
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}/0"


def _build_provider(redis_container) -> PipelineCacheProvider:
    suffix = uuid4().hex
    settings = PipelineCacheSettings(
        namespaces=CacheNamespaces(
            data=f"it-dataframe/data/{suffix}",
            data_index=f"it-dataframe/data_index/{suffix}",
            metadata=f"it-dataframe/metadata/{suffix}",
            metadata_index=f"it-dataframe/metadata_index/{suffix}",
        ),
        default_ttl=600,
        index_separator=":::",
    )
    data_codec = DumpEngineCodec()
    metadata_codec = DumpEngineCodec(dump_kwargs={"mode": "meta"})

    def _store_settings(key_prefix: str) -> RedisStoreSettings:
        return RedisStoreSettings(
            redis_url=_build_redis_url(redis_container),
            key_prefix=key_prefix,
            default_ttl=settings.default_ttl,
            idle_connection_ttl_sec=180,
            idle_sweep_interval_sec=30,
            separator=settings.index_separator,
        )

    return PipelineCacheProvider(
        settings=settings,
        data_blob_store=RedisBlobStore(_store_settings(settings.namespaces.data)),
        data_index_store=RedisIndexStore(
            serializer=data_codec.dump,
            deserializer=data_codec.load,
            settings=_store_settings(settings.namespaces.data_index),
        ),
        metadata_blob_store=RedisBlobStore(_store_settings(settings.namespaces.metadata)),
        metadata_index_store=RedisIndexStore(
            serializer=lambda value: value.encode("utf-8"),
            deserializer=lambda payload: payload.decode("utf-8"),
            settings=_store_settings(settings.namespaces.metadata_index),
        ),
        data_codec=data_codec,
        metadata_codec=metadata_codec,
    )


async def test_dataframe_data_preserves_saved_dataframe_column_types(
    redis_container,
    test_user_project,
) -> None:
    project_id = test_user_project.id
    node_id = "node-types"
    output_name = "output"

    provider = _build_provider(redis_container)
    facade = provider.create_facade()

    meta_df = pd.DataFrame(
        {
            "int_col": pd.Series(dtype="int64"),
            "float_col": pd.Series(dtype="float64"),
            "bool_col": pd.Series(dtype="bool"),
            "str_col": pd.Series(dtype="string"),
            "dt_col": pd.Series(dtype="datetime64[ns]"),
            "td_col": pd.Series(dtype="timedelta64[ns]"),
        }
    )
    saved_df = pd.DataFrame(
        {
            "int_col": [10, 20],
            "float_col": [1.1, 2.2],
            "bool_col": [True, False],
            "str_col": pd.Series(["foo", "bar"], dtype="string"),
            "dt_col": pd.to_datetime(["2026-02-01 10:00:00", "2026-02-01 11:00:00"]),
            "td_col": pd.to_timedelta(["00:00:01", "00:00:02"]),
        }
    )

    try:
        object_store = CodecObjectStore(provider.data_blob_store, provider.data_codec)
        cache = DataFrameExecutionCache(data_store=object_store)
        generation_id = uuid4().hex
        await cache.begin_output_generation(
            project_id=project_id,
            node_id=node_id,
            output_name=output_name,
            generation_id=generation_id,
            node_runtime_fingerprint="runtime:integration",
            meta=meta_df,
            npartitions=1,
            known_divisions=False,
            divisions=None,
        )
        descriptor = await cache.put_encoded_partition(
            project_id=project_id,
            node_id=node_id,
            output_name=output_name,
            generation_id=generation_id,
            part_no=0,
            rows=len(saved_df),
            payload=cache.encode_partition(saved_df),
        )
        await cache.commit_output_generation(
            project_id=project_id,
            node_id=node_id,
            output_name=output_name,
            generation_id=generation_id,
            partitions=(descriptor,),
        )
        await cache.stage_execution_snapshot(
            project_id=project_id,
            node_id=node_id,
            generation_id=generation_id,
            node_name="IntegrationNode",
            node_runtime_fingerprint="runtime:integration",
            output_names=(output_name,),
            dataframe_output_names=(output_name,),
            non_dataframe_outputs={},
            metadata={output_name: {}},
            execution_order=DataFrameExecutionOrder(queued_at_us=1, task_id=generation_id),
        )

        result = await dataframe_data(
            project_id=project_id,
            node_id=node_id,
            output_name=output_name,
            offset=0,
            limit=100,
            pipeline_cache=facade,
            project=test_user_project,
        )
    finally:
        await provider.data_blob_store.clear()
        await provider.data_index_store.clear()
        await provider.data_blob_store.close()
        await provider.data_index_store.close()

    columns_by_name = {column.name: column for column in result.columns}

    assert columns_by_name["int_col"].dtype == DataType.INT
    assert columns_by_name["float_col"].dtype == DataType.FLOAT
    assert columns_by_name["bool_col"].dtype == DataType.BOOLEAN
    assert columns_by_name["str_col"].dtype == DataType.STRING
    assert columns_by_name["dt_col"].dtype == DataType.DATETIME
    assert columns_by_name["td_col"].dtype == DataType.TIMEDELTA

    assert result.total_rows == 2
    assert result.total_partitions == 1
    assert len(result.values) == 2
    assert result.values[0][0] == 10
    assert result.values[1][0] == 20
