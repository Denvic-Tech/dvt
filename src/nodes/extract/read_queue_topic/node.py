import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import dask
import dask.dataframe as dd
import pandas as pd
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlmodel import Session

from core.metadata import get_df_metadata
from core.types import Column, DataFrameMetadata

from src.crud import queue_topic as queue_topic_crud
from src.db.session import (
    async_engine as default_async_metadata_engine,
    engine as default_metadata_engine,
)
from src.logger import logger
from src.managers.query_topic_manager import RedisTopicManager
from src.models import QueueTopicRecord
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO
from src.pipeline.execution_mode import PipelineExecutionMode

import config


class ReadQueueTopic(DFOutputBaseNode):
    TITLE = "Read Queue Topic"
    EMOJI = "📦"
    CATEGORY = "Extraction"

    topic_id: str = InputField(description="ID топика очереди")

    stream_key: str | None = InputField(
        default=None,
        description="Ключ потока в Redis (если не указан, формируется как 'queue_topic:{topic_id}:stream')"
    )

    delete_after_read: bool = InputField(default=False, description="Если True, удаляет прочитанные ID из Redis")

    count_limit: int | None = InputField(
        default=None,
        min_value=1,
        max_value=10_000_000,
        description="Общее максимальное количество сообщений (если указано, чтение остановится после этого числа)"
    )

    chunk_size: int = InputField(
        default=5000,
        min_value=1,
        max_value=100_000,
        description="Максимальное число сообщений за один XRANGE-запрос"
    )

    index_col: Optional[IO.COLUMN_NAME] = InputField(
        default=None,
        description="Колонка для использования в качестве индекса"
    )

    output: dd.DataFrame = OutputField()

    def __init__(self, *args, **kwargs):
        self.metadata_connection: Engine | AsyncEngine = default_metadata_engine
        self.metadata_connection_async: AsyncEngine = default_async_metadata_engine
        self._async_executor: ThreadPoolExecutor | None = None
        super().__init__(*args, **kwargs)

    def _run_async(self, coro):
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                if self._async_executor is None:
                    self._async_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="read-queue-topic")
                return self._async_executor.submit(lambda: asyncio.run(coro)).result()
        except RuntimeError:
            pass
        return asyncio.run(coro)

    async def _get_topic_async(self):
        async with AsyncSession(self.metadata_connection_async) as session:
            return (await queue_topic_crud.get_queue_topics_by(session, topic_id=self.topic_id)).first()

    def _get_topic(self):
        """Загружает топик из БД по topic_id."""
        topic = None
        if isinstance(self.metadata_connection, AsyncEngine):
            self.metadata_connection_async = self.metadata_connection
            topic = self._run_async(self._get_topic_async())
        else:
            # Fallback for sync engines (including in-memory SQLite tests).
            with Session(self.metadata_connection) as session:
                topic = session.get(QueueTopicRecord, self.topic_id)

        if not topic:
            raise ValueError(f"Топик с ID '{self.topic_id}' не найден в БД")
        return topic

    def _create_redis_manager(self) -> RedisTopicManager:
        """Создаёт новый менеджер Redis на основе глобального конфига."""
        return RedisTopicManager(decode_responses=True)

    def _read_range(self, redis_manager: RedisTopicManager, min_id: str, max_id: str,
                    limit: int | None = None) -> pd.DataFrame:
        """Читает диапазон сообщений из Redis Stream и возвращает pandas DataFrame."""
        try:
            return redis_manager.read_range_to_dataframe(
                self.stream_key,
                min_id,
                max_id,
                limit,
                self.chunk_size
            )
        finally:
            redis_manager.close()


    def _split_id_range(self, first_id: str, last_id: str, n: int) -> list[tuple[str, str]]:
        """Делит диапазон ID на n интервалов."""
        t_first = int(first_id.split('-')[0])
        t_last = int(last_id.split('-')[0])

        if n <= 1:
            return [(first_id, last_id)]

        if t_first == t_last:
            seq_first = int(first_id.split('-')[1])
            seq_last = int(last_id.split('-')[1])
            step = max(1, (seq_last - seq_first) // n)
            ranges = []
            prev = first_id
            for i in range(1, n):
                boundary_seq = seq_first + i * step
                if boundary_seq >= seq_last:
                    boundary_seq = seq_last - 1
                boundary = f"{t_first}-{boundary_seq}"
                ranges.append((prev, boundary))
                prev = boundary
            ranges.append((prev, last_id))
            return ranges
        else:
            step = max(1, (t_last - t_first) // n)
            ranges = []
            prev = first_id
            for i in range(1, n):
                boundary = str(t_first + i * step) + "-0"
                ranges.append((prev, boundary))
                prev = boundary
            ranges.append((prev, last_id))
            return ranges

    def process(self):
        topic = self._get_topic()

        self.stream_key = self.stream_key or f"queue_topic:{self.topic_id}:stream"
        redis_manager = self._create_redis_manager()

        try:
            total_messages = redis_manager.xlen(self.stream_key)
            logger.info(f"Stream {self.stream_key}: всего сообщений {total_messages}")

            if total_messages == 0:
                column_names = [col.name for col in topic.columns_schema]
                df = pd.DataFrame(columns=column_names)
                self.output = dd.from_pandas(df, npartitions=1)
                return

            limit_global = self.count_limit
            if limit_global and limit_global < total_messages:
                total_messages = limit_global

            target_rows = config.DASK_PARTITIONING.MIN_ROWS_PER_PART
            n_jobs = max(1, total_messages // target_rows)
            n_jobs = min(n_jobs, config.DASK_PARTITIONING.MAX_PARTITIONS)

            first_id, last_id = redis_manager.get_stream_bounds(self.stream_key)
            if first_id is None:
                df = pd.DataFrame()
            else:
                ranges = self._split_id_range(first_id, last_id, n_jobs)

                ranges_with_limit = []
                if limit_global:
                    per_job = limit_global // n_jobs
                    remaining = limit_global
                    for i, (mn, mx) in enumerate(ranges):
                        job_limit = per_job if i < n_jobs - 1 else remaining
                        ranges_with_limit.append((mn, mx, job_limit))
                        remaining -= job_limit
                else:
                    ranges_with_limit = [(mn, mx, None) for mn, mx in ranges]

                delayed_dfs = []
                for mn, mx, lim in ranges_with_limit:
                    delayed = dask.delayed(self._read_range)(
                        self._create_redis_manager(), mn, mx, lim
                    )
                    delayed_dfs.append(delayed)

                dfs = dask.compute(*delayed_dfs)
                df = pd.concat(dfs, ignore_index=True)

                if not df.empty and self.delete_after_read and self.execution_mode == PipelineExecutionMode.FULL:
                    ids_to_delete = df["_stream_id"].tolist()
                    redis_client = redis_manager._get_client()
                    batch_size = 5000
                    for i in range(0, len(ids_to_delete), batch_size):
                        batch = ids_to_delete[i:i + batch_size]
                        redis_client.xdel(self.stream_key, *batch)
                    logger.info(f"Удалено {len(ids_to_delete)} сообщений из {self.stream_key}")

                # 5. Постобработка
                expected_columns = [col.name for col in topic.columns_schema]

                if df.empty:
                    df = pd.DataFrame(columns=expected_columns)
                else:
                    # Приведение типов по схеме
                    for col in topic.columns_schema:
                        if col.name not in df.columns:
                            df[col.name] = None
                        else:
                            try:
                                dtype_upper = col.dtype.value.upper()
                                if dtype_upper in ("FLOAT", "DOUBLE", "DECIMAL"):
                                    df[col.name] = pd.to_numeric(df[col.name], errors='coerce')
                                elif dtype_upper in ("INT", "INTEGER", "BIGINT"):
                                    df[col.name] = pd.to_numeric(df[col.name], errors='coerce').astype("Int64")
                                elif dtype_upper in ("BOOL", "BOOLEAN"):
                                    def to_bool(val):
                                        if pd.isna(val): return None
                                        s = str(val).lower()
                                        return s in ("1", "true", "yes", "t")

                                    df[col.name] = df[col.name].apply(to_bool).astype("boolean")
                                elif dtype_upper in ("DATETIME", "TIMESTAMP"):
                                    df[col.name] = pd.to_datetime(df[col.name], errors='coerce')
                                else:
                                    df[col.name] = df[col.name].astype(str)
                            except Exception as e:
                                logger.warning(f"Ошибка типа в колонке {col.name}: {e}")

                    # Удаляем _stream_id перед финальным формированием, если он не выбран как индекс
                    if "_stream_id" in df.columns and self.index_col != "_stream_id":
                        df.drop(columns=["_stream_id"], inplace=True)

                    # Гарантируем только колонки из схемы (или + индекс)
                    current_expected = [c for c in expected_columns if c in df.columns]
                    df = df[current_expected]

            # 6. Индекс
            if self.index_col and self.index_col in df.columns:
                df.set_index(self.index_col, inplace=True)

            self.output = dd.from_pandas(df, npartitions=max(1, n_jobs))
            logger.info(f"Dask DataFrame готов: {len(df)} строк")

        finally:
            redis_manager.close()

    def infer_metadata(self):
        if isinstance(self.output, dd.DataFrame):
            return {"output": get_df_metadata(self.output)}

        try:
            topic = self._get_topic()

            columns = []
            for col in topic.columns_schema:
                columns.append(Column(
                    name=col.name,
                    dtype=col.dtype.value,
                    nullable=col.nullable
                ))

            metadata = DataFrameMetadata(columns=columns)
            return {"output": metadata}
        except Exception as e:
            logger.debug(f"Не удалось загрузить метаданные топика: {e}")
            return {"output": DataFrameMetadata(columns=[])}

    def __del__(self):
        if self._async_executor is not None:
            self._async_executor.shutdown(wait=False, cancel_futures=True)
