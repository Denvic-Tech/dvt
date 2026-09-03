from __future__ import annotations

from uuid import uuid4

import pandas as pd
import pytest
import sqlalchemy as sa
from tests.integration.src.nodes.extract.read_db_v3_matrix_helpers import (
    ALL_SQL_DB_ENGINE_FIXTURES,
    assert_strict_wide_types,
    assert_wide_result,
    build_wide_rows,
    dataframe_type_map,
    dialect_family,
    drop_table,
    resolved_sql_test_engine,
    seed_wide_table,
    table_name,
)

from src.modules.pipeline_cache import (
    CodecObjectStore,
    DumpEngineCodec,
    RedisBlobStore,
    RedisIndexStore,
    RedisStoreSettings,
)
from src.modules.pipeline_cache.domain.dataframe_cache import (
    ActiveDataFrameGeneration,
    CacheGenerationState,
    DataFrameCacheManifest,
    dataframe_active_key,
    dataframe_manifest_key,
)
from src.nodes.extract.read_table_from_db_v3 import ReadTableFromDBV3
from src.pipeline.execution_mode import PipelineExecutionMode

pytestmark = [pytest.mark.asyncio, pytest.mark.docker_required]


def _redis_url(redis_container) -> str:
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}/0"


def _store_settings(redis_container, prefix: str) -> RedisStoreSettings:
    return RedisStoreSettings(
        redis_url=_redis_url(redis_container),
        key_prefix=prefix,
        default_ttl=600,
        idle_connection_ttl_sec=180,
        idle_sweep_interval_sec=30,
        separator=":::",
    )


@pytest.mark.parametrize("resolved_sql_test_engine", ALL_SQL_DB_ENGINE_FIXTURES, indirect=True)
async def test_read_table_from_db_v3_caches_partitions_and_preserves_types(
    resolved_sql_test_engine: sa.Engine,
    redis_container,
) -> None:
    engine = resolved_sql_test_engine
    family = dialect_family(engine)
    target_table = table_name("table_cache", engine)
    rows = build_wide_rows(36)
    seed_wide_table(engine, target_table, rows)

    project_id = f"project-{uuid4().hex}"
    task_id = f"task-{uuid4().hex}"
    node_id = f"node-{uuid4().hex}"
    output_name = "output"

    data_codec = DumpEngineCodec()
    data_store = CodecObjectStore(
        RedisBlobStore(_store_settings(redis_container, f"it-read-table-cache/{uuid4().hex}")),
        data_codec,
    )
    data_index_store = RedisIndexStore(
        serializer=data_codec.dump,
        deserializer=data_codec.load,
        settings=_store_settings(redis_container, f"it-read-table-index/{uuid4().hex}"),
    )

    try:
        node = ReadTableFromDBV3(
            user_id="user",
            project_id=project_id,
            task_id=task_id,
            node_id=node_id,
            connection=engine,
            table_name=target_table,
            partition_col="id",
            npartitions=6,
            data_store=data_store,
            data_index_store=data_index_store,
            store_enabled=True,
        )

        await node.execute(PipelineExecutionMode.FULL)
        result = node.output.compute().reset_index(drop=True)

        assert_wide_result(result, expected_rows=len(rows))
        assert_strict_wide_types(result, family)

        await node.cache_execution_snapshot(
            outputs=node.get_outputs(),
            metadata=await node.resolve_metadata(),
        )
        active = await data_store.get(
            dataframe_active_key(project_id=project_id, node_id=node_id)
        )
        assert isinstance(active, ActiveDataFrameGeneration)
        manifest = await data_store.get(
            dataframe_manifest_key(
                project_id=project_id,
                node_id=node_id,
                output_name=output_name,
                generation_id=active.generation_id,
            )
        )
        assert isinstance(manifest, DataFrameCacheManifest)
        assert manifest.state == CacheGenerationState.READY
        assert dataframe_type_map(manifest.meta) == dataframe_type_map(node.output._meta)
        assert len(manifest.partitions) == node.output.npartitions
        assert manifest.known_divisions == node.output.known_divisions
        assert manifest.divisions == tuple(node.output.divisions)

        restored_parts: list[pd.DataFrame] = []
        for entry in manifest.partitions:
            cached_part = await data_store.get(entry.cache_key)
            assert isinstance(cached_part, pd.DataFrame)
            restored_parts.append(cached_part)

        restored_df = pd.concat(restored_parts, ignore_index=True)
        assert_wide_result(restored_df, expected_rows=len(rows))
        assert_strict_wide_types(restored_df, family)
    finally:
        await data_store.close()
        await data_index_store.close()
        drop_table(engine, target_table)
