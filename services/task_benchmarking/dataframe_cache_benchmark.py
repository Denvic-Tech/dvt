import argparse
import asyncio
import gc
import hashlib
import json
import math
import platform
import statistics
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import dask
import dask.dataframe as dd
import numpy as np
import pandas as pd
import psutil
import pyarrow
import redis.asyncio as redis

from core.dump_engine import dump as dump_object
from core.hashing import get_hash

from src.modules.pipeline_cache import (
    CodecObjectStore,
    DumpEngineCodec,
    RedisBlobStore,
    RedisIndexStore,
    RedisStoreSettings,
    create_dask_partition_fingerprint,
)
from src.modules.pipeline_cache.domain.dataframe_cache import (
    ActiveDataFrameGeneration,
    CacheGenerationState,
    DataFrameCacheManifest,
    dataframe_active_key,
    dataframe_manifest_key,
)
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.types import NodeOutput
from src.pipeline.execution_mode import PipelineExecutionMode

import config

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "tmp" / "task_benchmarking" / "dataframe_cache"
MEASURED_RUNS = 5
WARMUP_RUNS = 1
SCHEDULER = "threads"


class BenchmarkNode(DFOutputBaseNode):
    df_in: dd.DataFrame = InputField()
    output: dd.DataFrame = OutputField()

    def process(self) -> None:
        self.output = self.df_in.assign(__bench_value=self.df_in["value"] * 1.000001)


@dataclass
class Sample:
    wall_sec: float
    cpu_sec: float
    peak_rss_bytes: int
    final_rss_bytes: int
    result: float | int | None = None
    cache_keys: int | None = None
    cache_bytes: int | None = None
    redis_commands: dict[str, int] | None = None
    was_cache_generation_committed: bool | None = None
    partition_count_written: int | None = None
    manifest_state: str | None = None


class PeakRSSSampler:
    def __init__(self, interval_sec: float = 0.01) -> None:
        self.process = psutil.Process()
        self.interval_sec = interval_sec
        self.peak = self.process.memory_info().rss
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_sec):
            self.peak = max(self.peak, self.process.memory_info().rss)

    def __enter__(self) -> "PeakRSSSampler":
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join()
        self.peak = max(self.peak, self.process.memory_info().rss)


def redis_url() -> str:
    password = config.VALKEY.VALKEY_PASSWORD
    auth = f":{password}@" if password else ""
    return f"redis://{auth}{config.VALKEY.VALKEY_HOST}:{config.VALKEY.VALKEY_PORT}/{config.VALKEY.VALKEY_DB}"


def redis_settings(prefix: str) -> RedisStoreSettings:
    return RedisStoreSettings(
        redis_url=redis_url(),
        key_prefix=prefix,
        default_ttl=3600,
        idle_connection_ttl_sec=config.OTHER.REDIS_IDLE_CONNECTION_TTL_SEC,
        idle_sweep_interval_sec=config.OTHER.REDIS_IDLE_SWEEP_INTERVAL_SEC,
        separator=":::",
    )


@dataclass
class Stores:
    data: CodecObjectStore[Any]
    index: RedisIndexStore
    blob: RedisBlobStore

    async def clear(self) -> None:
        await self.data.clear()
        await self.index.clear()

    async def close(self) -> None:
        await self.data.close()
        await self.index.close()


def make_stores(token: str) -> Stores:
    codec = DumpEngineCodec()
    blob = RedisBlobStore(redis_settings(f"benchmark/df-cache/{token}/data"))
    index = RedisIndexStore(
        serializer=codec.dump,
        deserializer=codec.load,
        settings=redis_settings(f"benchmark/df-cache/{token}/index"),
    )
    return Stores(data=CodecObjectStore(blob, codec), index=index, blob=blob)


def make_numeric_ddf(*, rows: int, npartitions: int, known_divisions: bool = False) -> dd.DataFrame:
    pdf = pd.DataFrame(
        {
            "id": np.arange(rows, dtype=np.int64),
            "value": np.linspace(0.0, 1.0, rows, dtype=np.float64),
        }
    )
    if known_divisions:
        pdf = pdf.set_index("id", drop=False)
        pdf.index.name = "row_id"
    return dd.from_pandas(pdf, npartitions=npartitions, sort=known_divisions)


def make_wide_ddf(target_mb: int) -> tuple[dd.DataFrame, int]:
    rows = 65_536
    target_bytes = target_mb * 1024 * 1024
    numeric_bytes = rows * 16
    string_len = max(1, math.ceil((target_bytes - numeric_bytes) / rows))
    payload = "x" * string_len
    pdf = pd.DataFrame(
        {
            "id": np.arange(rows, dtype=np.int64),
            "value": np.arange(rows, dtype=np.float64),
            "payload": pd.Series([payload] * rows, dtype="string"),
        }
    )
    actual = int(pdf.memory_usage(index=True, deep=True).sum())
    return dd.from_pandas(pdf, npartitions=1), actual


def make_node(ddf: dd.DataFrame, stores: Stores, *, token: str, store_enabled: bool) -> BenchmarkNode:
    return BenchmarkNode(
        user_id="benchmark-user",
        project_id=f"benchmark-project-{token}",
        task_id=f"benchmark-task-{token}",
        node_id="benchmark-node",
        df_in=ddf,
        data_store=stores.data,
        data_index_store=stores.index,
        store_enabled=store_enabled,
    )


def timed_sync(fn: Callable[[], Any]) -> tuple[Any, float, float, int, int]:
    gc.collect()
    process = psutil.Process()
    start_cpu = time.process_time()
    start = time.perf_counter()
    with PeakRSSSampler() as rss:
        result = fn()
    wall = time.perf_counter() - start
    cpu = time.process_time() - start_cpu
    return result, wall, cpu, rss.peak, process.memory_info().rss


async def timed_async(fn: Callable[[], Any]) -> tuple[Any, float, float, int, int]:
    gc.collect()
    process = psutil.Process()
    start_cpu = time.process_time()
    start = time.perf_counter()
    with PeakRSSSampler() as rss:
        result = await fn()
    wall = time.perf_counter() - start
    cpu = time.process_time() - start_cpu
    return result, wall, cpu, rss.peak, process.memory_info().rss


async def commandstats(client: redis.Redis) -> dict[str, int]:
    info = await client.info("commandstats")
    return {
        key.removeprefix("cmdstat_"): int(value.get("calls", 0))
        for key, value in info.items()
        if isinstance(value, dict)
    }


def command_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    keys = set(before) | set(after)
    return {key: after.get(key, 0) - before.get(key, 0) for key in sorted(keys) if after.get(key, 0) != before.get(key, 0)}


async def prefix_metrics(client: redis.Redis, token: str) -> tuple[int, int]:
    patterns = [
        f"benchmark/df-cache/{token}/data/*",
        f"benchmark/df-cache/{token}/index:::*",
    ]
    keys: list[bytes] = []
    for pattern in patterns:
        async for key in client.scan_iter(match=pattern):
            keys.append(key)
    total = 0
    for key in keys:
        usage = await client.memory_usage(key)
        total += int(usage or 0)
    return len(keys), total


async def run_no_cache(rows: int, npartitions: int, token: str) -> Sample:
    stores = make_stores(token)
    client = redis.from_url(redis_url(), decode_responses=False)
    try:
        await stores.clear()
        ddf = make_numeric_ddf(rows=rows, npartitions=npartitions)
        node = make_node(ddf, stores, token=token, store_enabled=False)
        await node.execute(PipelineExecutionMode.FULL)
        before = await commandstats(client)
        result, wall, cpu, peak, final = timed_sync(
            lambda: float(node.output["__bench_value"].sum().compute(scheduler=SCHEDULER))
        )
        after = await commandstats(client)
        key_count, cache_bytes = await prefix_metrics(client, token)
        return Sample(wall, cpu, peak, final, result, key_count, cache_bytes, command_delta(before, after))
    finally:
        await stores.clear()
        await stores.close()
        await client.aclose()


async def populate_cache(ddf: dd.DataFrame, stores: Stores, token: str) -> BenchmarkNode:
    node = make_node(ddf, stores, token=token, store_enabled=True)
    await node.execute(PipelineExecutionMode.FULL)
    node.output.compute(scheduler=SCHEDULER)
    await node.cache_execution_snapshot(
        outputs={"output": NodeOutput(value=node.output)},
        metadata={"output": {"benchmark": True}},
    )
    return node


async def validate_committed_generation(
    node: BenchmarkNode,
    stores: Stores,
    *,
    expected_npartitions: int,
    expected_rows: int,
) -> dict[str, Any]:
    active = await stores.data.get(
        dataframe_active_key(project_id=node.project_id, node_id=node.node_id)
    )
    assert isinstance(active, ActiveDataFrameGeneration), "cache benchmark did not activate a generation"
    manifest = await stores.data.get(dataframe_manifest_key(
        project_id=node.project_id,
        node_id=node.node_id,
        output_name="output",
        generation_id=active.generation_id,
    ))
    assert isinstance(manifest, DataFrameCacheManifest), "cache benchmark manifest is missing"
    assert manifest.state == CacheGenerationState.READY
    assert manifest.npartitions == expected_npartitions
    assert len(manifest.partitions) == manifest.npartitions
    assert sum(manifest.rows_per_partition) == expected_rows
    assert await stores.data.has_many(part.cache_key for part in manifest.partitions)
    return {
        "generation_id": active.generation_id,
        "manifest_state": str(manifest.state),
        "partition_count_written": len(manifest.partitions),
        "rows_written": sum(manifest.rows_per_partition),
        "was_cache_generation_committed": True,
    }


async def run_cache_miss(rows: int, npartitions: int, token: str) -> Sample:
    stores = make_stores(token)
    client = redis.from_url(redis_url(), decode_responses=False)
    try:
        await stores.clear()
        ddf = make_numeric_ddf(rows=rows, npartitions=npartitions)
        node = make_node(ddf, stores, token=token, store_enabled=True)
        before = await commandstats(client)

        async def workload() -> float:
            await node.execute(PipelineExecutionMode.FULL)
            computed = node.output.compute(scheduler=SCHEDULER)
            value = float(computed["__bench_value"].sum())
            await node.cache_execution_snapshot(
                outputs={"output": NodeOutput(value=node.output)},
                metadata={"output": {"benchmark": True}},
            )
            await validate_committed_generation(
                node, stores, expected_npartitions=npartitions, expected_rows=rows
            )
            return value

        result, wall, cpu, peak, final = await timed_async(workload)
        validation = await validate_committed_generation(
            node, stores, expected_npartitions=npartitions, expected_rows=rows
        )
        after = await commandstats(client)
        key_count, cache_bytes = await prefix_metrics(client, token)
        return Sample(
            wall,
            cpu,
            peak,
            final,
            result,
            key_count,
            cache_bytes,
            command_delta(before, after),
            validation["was_cache_generation_committed"],
            validation["partition_count_written"],
            validation["manifest_state"],
        )
    finally:
        await stores.clear()
        await stores.close()
        await client.aclose()


async def run_optimized_downstream_aggregate(
    rows: int, npartitions: int, token: str
) -> dict[str, Any]:
    stores = make_stores(token)
    try:
        await stores.clear()
        node = make_node(
            make_numeric_ddf(rows=rows, npartitions=npartitions),
            stores,
            token=token,
            store_enabled=True,
        )

        async def workload() -> float:
            await node.execute(PipelineExecutionMode.FULL)
            value = float(node.output["__bench_value"].sum().compute(scheduler=SCHEDULER))
            await node.cache_execution_snapshot(
                outputs={"output": NodeOutput(value=node.output)},
                metadata={"output": {"benchmark": True}},
            )
            return value

        result, wall, cpu, peak, final = await timed_async(workload)
        active = await stores.data.get(
            dataframe_active_key(project_id=node.project_id, node_id=node.node_id)
        )
        partition_count = 0
        committed = isinstance(active, ActiveDataFrameGeneration)
        if committed:
            manifest = await stores.data.get(dataframe_manifest_key(
                project_id=node.project_id,
                node_id=node.node_id,
                output_name="output",
                generation_id=active.generation_id,
            ))
            if isinstance(manifest, DataFrameCacheManifest):
                partition_count = len(manifest.partitions)
        return {
            "sample": asdict(Sample(wall, cpu, peak, final, result)),
            "was_cache_generation_committed": committed,
            "partition_count_written": partition_count,
        }
    finally:
        await stores.clear()
        await stores.close()


async def run_cache_hit(rows: int, npartitions: int, token: str) -> dict[str, Sample | int | bool]:
    stores = make_stores(token)
    client = redis.from_url(redis_url(), decode_responses=False)
    try:
        await stores.clear()
        original = make_numeric_ddf(rows=rows, npartitions=npartitions, known_divisions=True)
        source_node = await populate_cache(original, stores, token)
        before = await commandstats(client)

        async def restore_only():
            return await DFOutputBaseNode.restore_execution_snapshot(
                project_id=source_node.project_id,
                node_id=source_node.node_id,
                node_name=source_node.__class__.__name__,
                expected_output_names=("output",),
                data_store=stores.data,
                data_index_store=stores.index,
            )

        restored, restore_wall, restore_cpu, restore_peak, restore_final = await timed_async(restore_only)
        after_restore = await commandstats(client)
        assert restored is not None
        restored_ddf = restored.outputs["output"].value

        first, first_wall, first_cpu, first_peak, first_final = timed_sync(
            lambda: restored_ddf.get_partition(0).compute(scheduler=SCHEDULER)
        )
        _ = first
        after_first = await commandstats(client)
        result, downstream_wall, downstream_cpu, downstream_peak, downstream_final = timed_sync(
            lambda: float(restored_ddf["__bench_value"].sum().compute(scheduler=SCHEDULER))
        )
        after_downstream = await commandstats(client)
        key_count, cache_bytes = await prefix_metrics(client, token)
        return {
            "restore": Sample(
                restore_wall,
                restore_cpu,
                restore_peak,
                restore_final,
                None,
                key_count,
                cache_bytes,
                command_delta(before, after_restore),
            ),
            "first_partition": Sample(
                first_wall,
                first_cpu,
                first_peak,
                first_final,
                len(first),
                key_count,
                cache_bytes,
                command_delta(after_restore, after_first),
            ),
            "downstream": Sample(
                downstream_wall,
                downstream_cpu,
                downstream_peak,
                downstream_final,
                result,
                key_count,
                cache_bytes,
                command_delta(after_first, after_downstream),
            ),
            "original_known_divisions": original.known_divisions,
            "restored_known_divisions": restored_ddf.known_divisions,
            "restored_npartitions": restored_ddf.npartitions,
        }
    finally:
        await stores.clear()
        await stores.close()
        await client.aclose()


async def run_wide_cache_miss(target_mb: int, token: str) -> dict[str, Any]:
    stores = make_stores(token)
    try:
        await stores.clear()
        ddf, actual = make_wide_ddf(target_mb)
        node = make_node(ddf, stores, token=token, store_enabled=True)

        async def workload() -> int:
            await node.execute(PipelineExecutionMode.FULL)
            computed = node.output.compute(scheduler=SCHEDULER)
            rows = len(computed)
            await node.cache_execution_snapshot(
                outputs={"output": NodeOutput(value=node.output)},
                metadata={"output": {"benchmark": True}},
            )
            await validate_committed_generation(
                node, stores, expected_npartitions=1, expected_rows=rows
            )
            return rows

        result, wall, cpu, peak, final = await timed_async(workload)
        return {"actual_partition_bytes": actual, "sample": asdict(Sample(wall, cpu, peak, final, result))}
    finally:
        await stores.clear()
        await stores.close()


async def run_known_divisions_ops(rows: int, npartitions: int, token: str) -> dict[str, Any]:
    stores = make_stores(token)
    try:
        await stores.clear()
        original = make_numeric_ddf(rows=rows, npartitions=npartitions, known_divisions=True)
        node = await populate_cache(original, stores, token)
        restored = await DFOutputBaseNode.restore_execution_snapshot(
            project_id=node.project_id,
            node_id=node.node_id,
            node_name=node.__class__.__name__,
            expected_output_names=("output",),
            data_store=stores.data,
            data_index_store=stores.index,
        )
        assert restored is not None
        cached = restored.outputs["output"].value
        start = rows // 3
        stop = start + max(100, rows // 100)

        def loc_time(ddf: dd.DataFrame) -> float:
            _, wall, *_ = timed_sync(lambda: ddf.loc[start:stop].compute(scheduler=SCHEDULER))
            return wall

        right_pdf = pd.DataFrame({"id": np.arange(rows, dtype=np.int64), "rhs": np.ones(rows)}).set_index("id")
        right = dd.from_pandas(right_pdf, npartitions=npartitions, sort=True)

        def join_time(ddf: dd.DataFrame) -> float:
            _, wall, *_ = timed_sync(lambda: ddf.join(right, how="inner").head(1000, compute=True))
            return wall

        return {
            "original_known_divisions": original.known_divisions,
            "restored_known_divisions": cached.known_divisions,
            "original_divisions": list(original.divisions),
            "restored_divisions": list(cached.divisions),
            "loc_original_sec": loc_time(original),
            "loc_restored_sec": loc_time(cached),
            "join_original_sec": join_time(original),
            "join_restored_sec": join_time(cached),
        }
    finally:
        await stores.clear()
        await stores.close()


async def correctness_probes(token: str) -> dict[str, Any]:
    results: dict[str, Any] = {}

    # >500k truncation in the execution codec used by the current cache.
    pdf = pd.DataFrame({"value": np.arange(500_003, dtype=np.int64)})
    payload = dump_object(pdf)
    from core.dump_engine import load as load_object

    loaded = load_object(payload)
    results["truncation"] = {
        "input_rows": len(pdf),
        "cached_rows": len(loaded),
        "lossless": len(loaded) == len(pdf),
    }

    # Same expr/schema/shape but different values.
    a = pd.DataFrame({"value": [1, 2, 3]})
    b = pd.DataFrame({"value": [100, 200, 300]})
    key_a = create_dask_partition_fingerprint(a, expr_name="same-expr", node_name="Node", part_no=0, npartitions=1)
    key_b = create_dask_partition_fingerprint(b, expr_name="same-expr", node_name="Node", part_no=0, npartitions=1)
    results["partition_identity"] = {"key_a": key_a, "key_b": key_b, "collision": key_a == key_b}
    results["shallow_hash_equal"] = get_hash(a, deep=False) == get_hash(b, deep=False)

    # End-to-end restore + laziness / known divisions.
    stores = make_stores(f"{token}-correctness")
    try:
        await stores.clear()
        original = make_numeric_ddf(rows=20_000, npartitions=8, known_divisions=True)
        node = await populate_cache(original, stores, f"{token}-correctness")

        class CountingStore:
            def __init__(self, delegate):
                self.delegate = delegate
                self.get_keys: list[str] = []

            async def get(self, key):
                self.get_keys.append(key)
                return await self.delegate.get(key)

            async def put(self, *args, **kwargs):
                return await self.delegate.put(*args, **kwargs)

            async def remove(self, *args, **kwargs):
                return await self.delegate.remove(*args, **kwargs)

        counting = CountingStore(stores.data)
        restored = await DFOutputBaseNode.restore_execution_snapshot(
            project_id=node.project_id,
            node_id=node.node_id,
            node_name=node.__class__.__name__,
            expected_output_names=("output",),
            data_store=counting,
            data_index_store=stores.index,
        )
        assert restored is not None
        results["restore_laziness"] = {
            "get_count_before_compute": len(counting.get_keys),
            "partition_blob_gets_before_compute": sum("dd_part:" in key for key in counting.get_keys),
            "npartitions": original.npartitions,
            "lazy": sum("dd_part:" in key for key in counting.get_keys) == 0,
        }
        cached = restored.outputs["output"].value
        results["divisions"] = {
            "original_known": original.known_divisions,
            "restored_known": cached.known_divisions,
            "original": list(original.divisions),
            "restored": list(cached.divisions),
        }

        active = await stores.data.get(
            dataframe_active_key(project_id=node.project_id, node_id=node.node_id)
        )
        assert isinstance(active, ActiveDataFrameGeneration)
        manifest = await stores.data.get(dataframe_manifest_key(
            project_id=node.project_id,
            node_id=node.node_id,
            output_name="output",
            generation_id=active.generation_id,
        ))
        assert isinstance(manifest, DataFrameCacheManifest)
        await stores.data.remove(manifest.partitions[0].cache_key)
        missing_restore = await DFOutputBaseNode.restore_execution_snapshot(
            project_id=node.project_id,
            node_id=node.node_id,
            node_name=node.__class__.__name__,
            expected_output_names=("output",),
            data_store=stores.data,
            data_index_store=stores.index,
        )
        results["missing_partition_restore"] = {"returned_none": missing_restore is None}
    finally:
        await stores.clear()
        await stores.close()

    # Cache write failures currently propagate through the callback lifecycle.
    class FailingStore:
        async def put(self, *_args, **_kwargs):
            raise RuntimeError("intentional cache backend failure")

        async def get(self, *_args, **_kwargs):
            return None

        async def remove(self, *_args, **_kwargs):
            return None

    class NoopIndex:
        async def put(self, *_args, **_kwargs):
            return None

        async def query(self, *_args, **_kwargs):
            return []

        async def remove(self, *_args, **_kwargs):
            return None

    failure_node = BenchmarkNode(
        user_id="benchmark-user",
        project_id="failure-project",
        task_id="failure-task",
        node_id="failure-node",
        df_in=make_numeric_ddf(rows=10_000, npartitions=4),
        data_store=FailingStore(),
        data_index_store=NoopIndex(),
        store_enabled=True,
    )
    try:
        await failure_node.execute(PipelineExecutionMode.FULL)
        failure_node.output.compute(scheduler=SCHEDULER)
    except Exception as exc:
        results["cache_write_failure"] = {"pipeline_survived": False, "error_type": type(exc).__name__, "error": str(exc)}
    else:
        results["cache_write_failure"] = {"pipeline_survived": True}

    return results


def summarize_samples(samples: list[Sample]) -> dict[str, Any]:
    walls = [sample.wall_sec for sample in samples]
    cpus = [sample.cpu_sec for sample in samples]
    peaks = [sample.peak_rss_bytes for sample in samples]
    cache_bytes = [sample.cache_bytes for sample in samples if sample.cache_bytes is not None]
    cache_keys = [sample.cache_keys for sample in samples if sample.cache_keys is not None]

    def stats(values: list[float | int]) -> dict[str, float]:
        sorted_values = sorted(float(value) for value in values)
        return {
            "median": statistics.median(sorted_values),
            "min": min(sorted_values),
            "max": max(sorted_values),
            "p25": float(np.percentile(sorted_values, 25)),
            "p75": float(np.percentile(sorted_values, 75)),
        }

    result: dict[str, Any] = {
        "wall_sec": stats(walls),
        "cpu_sec": stats(cpus),
        "peak_rss_bytes": stats(peaks),
        "samples": [asdict(sample) for sample in samples],
    }
    if cache_bytes:
        result["cache_bytes"] = stats(cache_bytes)
    if cache_keys:
        result["cache_keys"] = stats(cache_keys)
    return result


async def repeated(label: str, fn: Callable[[int], Any], measured: int) -> dict[str, Any]:
    for index in range(WARMUP_RUNS):
        await fn(-(index + 1))
    samples: list[Sample] = []
    for index in range(measured):
        sample = await fn(index)
        samples.append(sample)
        print(f"{label}: {index + 1}/{measured} wall={sample.wall_sec:.4f}s peak={sample.peak_rss_bytes / 2**20:.1f} MiB", flush=True)
    return summarize_samples(samples)


async def repeated_hit(label: str, fn: Callable[[int], Any], measured: int) -> dict[str, Any]:
    for index in range(WARMUP_RUNS):
        await fn(-(index + 1))
    runs = []
    for index in range(measured):
        result = await fn(index)
        runs.append(result)
        downstream: Sample = result["downstream"]
        print(f"{label}: {index + 1}/{measured} downstream={downstream.wall_sec:.4f}s peak={downstream.peak_rss_bytes / 2**20:.1f} MiB", flush=True)
    result = {
        "restore": summarize_samples([run["restore"] for run in runs]),
        "first_partition": summarize_samples([run["first_partition"] for run in runs]),
        "downstream": summarize_samples([run["downstream"] for run in runs]),
        "original_known_divisions": runs[-1]["original_known_divisions"],
        "restored_known_divisions": runs[-1]["restored_known_divisions"],
        "restored_npartitions": runs[-1]["restored_npartitions"],
    }
    result["restore_plus_first_partition_median_sec"] = (
        result["restore"]["wall_sec"]["median"]
        + result["first_partition"]["wall_sec"]["median"]
    )
    result["restore_plus_downstream_median_sec"] = (
        result["restore"]["wall_sec"]["median"]
        + result["downstream"]["wall_sec"]["median"]
    )
    return result


def git_metadata() -> dict[str, Any]:
    def run(*args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    status = run("status", "--porcelain")
    diff = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--binary", "HEAD"],
        check=True,
        capture_output=True,
    ).stdout
    script_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {
        "git_head": run("rev-parse", "HEAD"),
        "git_dirty": bool(status),
        "git_diff_hash": hashlib.sha256(diff).hexdigest(),
        "branch": run("branch", "--show-current"),
        "benchmark_script_hash": script_hash,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["before", "after"], required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--measured-runs", type=int, default=MEASURED_RUNS)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    run_id = args.run_id or f"{time.strftime('%Y%m%dT%H%M%S')}_{args.phase}"
    output_dir = DEFAULT_OUTPUT / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    token_root = f"{args.phase}-{uuid.uuid4().hex[:10]}"
    measured = max(1, args.measured_runs)

    client = redis.from_url(redis_url(), decode_responses=False)
    pong = await client.ping()
    redis_info = await client.info("server")
    memory_info = await client.info("memory")
    await client.aclose()

    env = {
        "phase": args.phase,
        "run_id": run_id,
        **git_metadata(),
        "python": platform.python_version(),
        "python_full": platform.python_version_tuple(),
        "dask": dask.__version__,
        "pandas": pd.__version__,
        "pyarrow": pyarrow.__version__,
        "platform": platform.platform(),
        "cpu": platform.processor(),
        "cpu_physical": psutil.cpu_count(logical=False),
        "cpu_logical": psutil.cpu_count(logical=True),
        "ram_bytes": psutil.virtual_memory().total,
        "scheduler": SCHEDULER,
        "warmup_runs": WARMUP_RUNS,
        "measured_runs": measured,
        "valkey_ping": bool(pong),
        "redis_version": redis_info.get("redis_version"),
        "redis_mode": redis_info.get("redis_mode"),
        "redis_maxmemory": memory_info.get("maxmemory"),
    }

    results: dict[str, Any] = {"environment": env, "correctness": await correctness_probes(token_root), "scenarios": {}}

    rows = 1_000_000 if not args.quick else 200_000
    parts = 16
    results["scenarios"]["no_cache"] = await repeated(
        "no_cache",
        lambda i: run_no_cache(rows, parts, f"{token_root}-nocache-{i}"),
        measured,
    )
    results["scenarios"]["cache_miss"] = await repeated(
        "cache_miss",
        lambda i: run_cache_miss(rows, parts, f"{token_root}-miss-{i}"),
        measured,
    )
    optimized_runs = []
    for i in range(WARMUP_RUNS):
        await run_optimized_downstream_aggregate(
            rows, parts, f"{token_root}-optimized-warm-{i}"
        )
    for i in range(measured):
        optimized_runs.append(await run_optimized_downstream_aggregate(
            rows, parts, f"{token_root}-optimized-{i}"
        ))
    results["scenarios"]["optimized_downstream_aggregate"] = {"runs": optimized_runs}
    results["scenarios"]["cache_hit"] = await repeated_hit(
        "cache_hit",
        lambda i: run_cache_hit(rows, parts, f"{token_root}-hit-{i}"),
        measured,
    )

    partition_counts = [1, 100, 500] if args.quick else [1, 100, 500, 1000]
    for count in partition_counts:
        scenario_rows = max(count * 1000, 100_000)
        results["scenarios"][f"cache_hit_{count}_parts"] = await repeated_hit(
            f"cache_hit_{count}_parts",
            lambda i, c=count, r=scenario_rows: run_cache_hit(r, c, f"{token_root}-hit-{c}-{i}"),
            measured,
        )

    large_rows_cases = [500_003] if args.quick else [500_003, 1_000_000]
    for row_count in large_rows_cases:
        results["scenarios"][f"large_partition_{row_count}_rows"] = await repeated(
            f"large_partition_{row_count}_rows",
            lambda i, r=row_count: run_cache_miss(r, 1, f"{token_root}-rows-{r}-{i}"),
            measured,
        )

    wide_targets = [8, 16] if args.quick else [8, 16, 32, 64]
    for target in wide_targets:
        # One warm-up + measured runs, retaining actual generated partition bytes.
        wide_runs = []
        for i in range(WARMUP_RUNS):
            await run_wide_cache_miss(target, f"{token_root}-wide-{target}-warm-{i}")
        for i in range(measured):
            wide_runs.append(await run_wide_cache_miss(target, f"{token_root}-wide-{target}-{i}"))
            print(f"wide_{target}mb: {i + 1}/{measured}", flush=True)
        results["scenarios"][f"wide_partition_{target}mb"] = {
            "actual_partition_bytes": wide_runs[-1]["actual_partition_bytes"],
            "samples": [run["sample"] for run in wide_runs],
            "summary": summarize_samples([Sample(**run["sample"]) for run in wide_runs]),
        }

    known_runs = []
    for i in range(WARMUP_RUNS):
        await run_known_divisions_ops(200_000 if args.quick else 1_000_000, 16, f"{token_root}-div-warm-{i}")
    for i in range(measured):
        known_runs.append(await run_known_divisions_ops(200_000 if args.quick else 1_000_000, 16, f"{token_root}-div-{i}"))
        print(f"known_divisions: {i + 1}/{measured}", flush=True)
    results["scenarios"]["known_divisions"] = {
        "runs": known_runs,
        "loc_original_median_sec": statistics.median(run["loc_original_sec"] for run in known_runs),
        "loc_restored_median_sec": statistics.median(run["loc_restored_sec"] for run in known_runs),
        "join_original_median_sec": statistics.median(run["join_original_sec"] for run in known_runs),
        "join_restored_median_sec": statistics.median(run["join_restored_sec"] for run in known_runs),
        "original_known_divisions": known_runs[-1]["original_known_divisions"],
        "restored_known_divisions": known_runs[-1]["restored_known_divisions"],
    }

    if not args.quick:
        rss_runs = []
        for i in range(20):
            rss_run = await run_cache_hit(
                200_000,
                16,
                f"{token_root}-rss-drift-{i}",
            )
            rss_runs.append(rss_run["downstream"].final_rss_bytes)
            print(f"rss_drift: {i + 1}/20", flush=True)
        results["scenarios"]["rss_drift_20_runs"] = {
            "final_rss_bytes": rss_runs,
            "first": rss_runs[0],
            "last": rss_runs[-1],
            "delta": rss_runs[-1] - rss_runs[0],
            "min": min(rss_runs),
            "max": max(rss_runs),
        }

    output_path = output_dir / "report.json"
    output_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    (output_dir / "env.json").write_text(json.dumps(env, indent=2, default=str), encoding="utf-8")
    print(f"REPORT={output_path}")


if __name__ == "__main__":
    asyncio.run(main())
