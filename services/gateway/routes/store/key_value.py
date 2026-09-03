import uuid
import fnmatch
from typing import List, Dict, Optional

from fastapi import Depends, HTTPException, APIRouter, Request, Query
from redis.asyncio import Redis

from services.gateway.deps.redis import get_redis_bytes
from src.schemas.http.store import BatchItem

r = router = APIRouter()

INDEX_KEY = "store:index"
SEQ_KEY = "store:seq"


@r.post("/batch", status_code=201)
async def set_data_batch(
        items: List[BatchItem],
        ttl: Optional[int] = Query(None, description="Время жизни ключей в секундах (опционально)"),
        redis: Redis = Depends(get_redis_bytes)
):
    """
    Пакетная запись.
    Если ttl передан — используем Pipeline (так как MSET не поддерживает TTL).
    Если ttl нет — используем MSET.
    """
    if not items:
        raise HTTPException(status_code=400, detail="Empty items list")

    if ttl:
        # Вариант с TTL: используем Pipeline
        async with redis.pipeline(transaction=True) as pipe:
            for item in items:
                await pipe.set(item.key, item.value, ex=ttl)
                await pipe.incr(SEQ_KEY)

            results = await pipe.execute()

        # извлекаем seq
        seq_values = results[1::2]

        mapping = {
            item.key: seq
            for item, seq in zip(items, seq_values)
        }

        await redis.zadd(INDEX_KEY, mapping)
        processed_count = len(items)

    else:
        # Вариант без TTL: используем MSET
        mapping = {item.key: item.value for item in items}
        await redis.mset(mapping)
        seqs = [await redis.incr(SEQ_KEY) for _ in items]
        await redis.zadd(
            INDEX_KEY,
            {item.key: seq for item, seq in zip(items, seqs)}
        )
        processed_count = len(items)

    return {
        "status": "ok",
        "processed": processed_count,
        "method": "pipeline_with_ttl" if ttl else "mset"
    }


@r.post("", status_code=201)
async def set_data(
        key: str = Query(..., description="Базовая часть ключа"),
        extend_key: bool = Query(False, description="Добавить случайный хвост к ключу?"),
        ttl: Optional[int] = Query(None, description="Время жизни ключа в секундах (опционально)"),
        request: Request = None,
        redis: Redis = Depends(get_redis_bytes)
):
    """
    Запись одной записи с опциональным TTL.
    """
    body_bytes = await request.body()
    if not body_bytes:
        raise HTTPException(status_code=400, detail="Empty body")

    try:
        # Декодируем байты в строку
        value = body_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Body must be a valid UTF-8 string")

    # Логика расширения ключа
    final_key = key
    if extend_key:
        # Генерируем короткий хвост (8 символов от UUID)
        random_tail = uuid.uuid4().hex[:8]
        final_key = f"{key}:{random_tail}"

    # Записываем с TTL, если он передан (ex=ttl)
    await redis.set(final_key, value, ex=ttl)

    # Индекс
    seq = await redis.incr(SEQ_KEY)
    await redis.zadd(INDEX_KEY, {final_key: seq})

    return {
        "status": "ok",
        "key": final_key,
        "ttl": ttl
    }


@r.get("", response_model=Dict[str, str])
async def get_data(
        pattern: str = Query("*", description="Паттерн для поиска"),
        limit: int = Query(10, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        redis: Redis = Depends(get_redis_bytes)
):
    # читаем все ключи из индекса (упорядочено)
    keys = await redis.zrange(INDEX_KEY, 0, -1)
    if not keys:
        return {}
    decoded_keys = [
        k.decode() if isinstance(k, bytes) else k
        for k in keys
    ]
    filtered = [
        k for k in decoded_keys
        if fnmatch.fnmatch(k, pattern)
    ]
    target_keys = filtered[offset:offset + limit]

    if not target_keys:
        return {}

    values = await redis.mget(target_keys)

    result = {}
    missing_keys = []
    for k, v in zip(target_keys, values):
        if v is None:
            # TTL истёк → чистим индекс
            missing_keys.append(k)
            continue

        result[k] = v.decode() if isinstance(v, bytes) else v

    if missing_keys:
        await redis.zrem(INDEX_KEY, *missing_keys)

    return result


@r.delete("")
async def delete_data(
        key: Optional[str] = Query(None),
        keys: Optional[List[str]] = Query(None),
        pattern: Optional[str] = Query(None),
        redis: Redis = Depends(get_redis_bytes)
):
    deleted_total = 0
    if key:
        deleted_total += await redis.delete(key)
        await redis.zrem(INDEX_KEY, key)
    if keys:
        deleted_total += await redis.delete(*keys)
        await redis.zrem(INDEX_KEY, *keys)
    if pattern:
        batch = []
        async for p_key in redis.scan_iter(match=pattern, count=500):
            batch.append(p_key)
            if len(batch) >= 500:
                deleted_total += await redis.delete(*batch)
                await redis.zrem(INDEX_KEY, *batch)
                batch = []
        if batch:
            deleted_total += await redis.delete(*batch)
            await redis.zrem(INDEX_KEY, *batch)

    if not (key or keys or pattern):
        raise HTTPException(status_code=400, detail="Provide key, keys or pattern")

    return {"status": "ok", "deleted_count": deleted_total}
