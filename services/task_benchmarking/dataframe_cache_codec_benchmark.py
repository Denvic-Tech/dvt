import argparse
import asyncio
import json
import statistics
import time
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import redis.asyncio as redis

import config
from src.modules.pipeline_cache import DumpEngineCodec, RedisBlobStore, RedisStoreSettings

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tmp" / "task_benchmarking" / "dataframe_cache"
TARGETS_MB = (8, 16, 32, 64)
WARMUPS = 1
RUNS = 5


def _url():
    auth = f":{config.VALKEY.VALKEY_PASSWORD}@" if config.VALKEY.VALKEY_PASSWORD else ""
    return f"redis://{auth}{config.VALKEY.VALKEY_HOST}:{config.VALKEY.VALKEY_PORT}/{config.VALKEY.VALKEY_DB}"


def _settings(prefix):
    return RedisStoreSettings(
        redis_url=_url(), key_prefix=prefix, default_ttl=3600,
        idle_connection_ttl_sec=config.OTHER.REDIS_IDLE_CONNECTION_TTL_SEC,
        idle_sweep_interval_sec=config.OTHER.REDIS_IDLE_SWEEP_INTERVAL_SEC,
        separator=":::"
    )


def _frame(target_mb):
    rows = 65_536
    target = target_mb * 1024 * 1024
    payload_len = max(1, (target - rows * 16) // rows)
    pdf = pd.DataFrame({
        "id": np.arange(rows, dtype=np.int64),
        "value": np.arange(rows, dtype=np.float64),
        "payload": pd.Series(["x" * payload_len] * rows, dtype="string"),
    })
    return pdf, int(pdf.memory_usage(index=True, deep=True).sum())


def _stats(values):
    return {"median": statistics.median(values), "min": min(values), "max": max(values)}


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--phase", choices=("before", "after"), required=True)
    p.add_argument("--run-id", required=True)
    args = p.parse_args()
    codec = DumpEngineCodec()
    report = {"phase": args.phase, "targets": {}}
    for target_mb in TARGETS_MB:
        pdf, frame_bytes = _frame(target_mb)
        prefix = f"benchmark/df-cache-codec/{args.phase}-{uuid.uuid4().hex[:8]}-{target_mb}"
        store = RedisBlobStore(_settings(prefix))
        client = redis.from_url(_url(), decode_responses=False)
        try:
            enc_times, write_times, read_times, decode_times, payload_sizes = [], [], [], [], []
            for i in range(WARMUPS + RUNS):
                t0 = time.perf_counter(); payload = codec.dump(pdf); enc = time.perf_counter() - t0
                key = f"part-{i}"
                t0 = time.perf_counter(); await store.put(key, payload, ttl=3600); write = time.perf_counter() - t0
                t0 = time.perf_counter(); loaded_payload = await store.get(key); read = time.perf_counter() - t0
                t0 = time.perf_counter(); loaded = codec.load(loaded_payload); decode = time.perf_counter() - t0
                assert len(loaded) == len(pdf)
                if i >= WARMUPS:
                    enc_times.append(enc); write_times.append(write); read_times.append(read); decode_times.append(decode); payload_sizes.append(len(payload))
            keys = [key async for key in client.scan_iter(match=f"{prefix}/*")]
            memory = 0
            for redis_key in keys:
                memory += int(await client.memory_usage(redis_key) or 0)
            report["targets"][str(target_mb)] = {
                "frame_bytes": frame_bytes,
                "payload_bytes": _stats(payload_sizes),
                "serialize_sec": _stats(enc_times),
                "redis_write_sec": _stats(write_times),
                "redis_read_sec": _stats(read_times),
                "deserialize_sec": _stats(decode_times),
                "redis_key_count": len(keys),
                "redis_memory_bytes": memory,
            }
            print(target_mb, report["targets"][str(target_mb)], flush=True)
        finally:
            await store.clear(); await store.close(); await client.aclose()
    out = OUT / args.run_id / "codec_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"REPORT={out}")


if __name__ == "__main__":
    asyncio.run(main())
