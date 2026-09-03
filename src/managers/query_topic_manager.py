from typing import Optional, List
import pandas as pd
import redis
from redis.client import Redis

import config
from src.logger import logger


def _build_redis_url() -> str:
    """Формирует URL для подключения к Redis/Valkey из конфига."""
    auth = f":{config.VALKEY.VALKEY_PASSWORD}@" if config.VALKEY.VALKEY_PASSWORD else ""
    return f"redis://{auth}{config.VALKEY.VALKEY_HOST}:{config.VALKEY.VALKEY_PORT}/{config.VALKEY.VALKEY_DB}"


class RedisTopicManager:
    """Менеджер для работы с Redis Stream. Создаётся заново на каждый вызов."""

    def __init__(self, decode_responses: bool = True):
        self.decode_responses = decode_responses
        self._client: Optional[Redis] = None

    def _get_client(self) -> Redis:
        """Создаёт и возвращает синхронный клиент Redis из конфига."""
        if self._client is None:
            self._client = redis.Redis.from_url(
                _build_redis_url(),
                decode_responses=self.decode_responses,
                socket_timeout=5,
                socket_connect_timeout=5,
                retry_on_timeout=True
            )
        return self._client

    def close(self):
        """Закрывает соединение с Redis."""
        if self._client:
            self._client.close()
            self._client = None

    def xlen(self, stream_key: str) -> int:
        """Возвращает количество сообщений в потоке."""
        return self._get_client().xlen(stream_key)

    def xrange(
            self,
            stream_key: str,
            min_id: str = "-",
            max_id: str = "+",
            count: Optional[int] = None
    ) -> List[tuple]:
        """Читает сообщения из потока по диапазону."""
        return self._get_client().xrange(stream_key, min=min_id, max=max_id, count=count)

    def xrevrange(
            self,
            stream_key: str,
            max_id: str = "+",
            min_id: str = "-",
            count: Optional[int] = None
    ) -> List[tuple]:
        """Читает сообщения из потока в обратном порядке."""
        return self._get_client().xrevrange(stream_key, max=max_id, min=min_id, count=count)

    def get_stream_bounds(self, stream_key: str) -> tuple[Optional[str], Optional[str]]:
        """Возвращает (первый_id, последний_id) для потока. Если поток пуст -> (None, None)."""
        first = self.xrange(stream_key, min_id="-", max_id="+", count=1)
        if not first:
            return None, None
        first_id = first[0][0]
        last = self.xrevrange(stream_key, max_id="+", min_id="-", count=1)
        last_id = last[0][0]
        return first_id, last_id

    def read_range_to_dataframe(
            self,
            stream_key: str,
            min_id: str,
            max_id: str,
            limit: Optional[int] = None,
            chunk_size: int = 5000
    ) -> pd.DataFrame:
        """
        Читает диапазон сообщений из Redis Stream и возвращает pandas DataFrame.
        """
        try:
            messages = self.xrange(
                stream_key,
                min_id=min_id,
                max_id=max_id,
                count=limit or chunk_size
            )
        except redis.RedisError as e:
            logger.error(f"Ошибка чтения Redis Stream {stream_key} [{min_id}:{max_id}]: {e}")
            raise

        records = []
        for msg_id, fields in messages:
            record = {"_stream_id": msg_id}

            # fields - это уже ГОТОВЫЙ СЛОВАРЬ!
            if isinstance(fields, dict):
                record.update(fields)  # Просто обновляем словарь
            elif isinstance(fields, list):
                # На случай, если где-то всё-таки список
                for i in range(0, len(fields), 2):
                    if i + 1 < len(fields):
                        record[fields[i]] = fields[i + 1]
            else:
                logger.error(f"Неизвестный тип fields: {type(fields)}")
                continue

            records.append(record)

        return pd.DataFrame(records)