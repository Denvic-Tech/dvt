import asyncio
import sys
from typing import Optional, List, Dict, Any, Callable

from loguru import logger as loguru_logger
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from src.logger.formatters import sink_formatter
import config


_SENTINEL = object()


class BatchedDBSink:
    """
    Асинхронный батчевый sink для Loguru:
    - __call__ вызывается из потока Loguru (enqueue=True)
    - внутри мы через run_coroutine_threadsafe складываем записи в asyncio.Queue
    - отдельная корутина _run периодически флашит батчи в БД через AsyncEngine
    - при ошибках просто логируем warning и дропаем записи
    """

    def __init__(
        self,
        engine: AsyncEngine,
        service_name: str,
        *,
        loop: asyncio.AbstractEventLoop,
        batch_size: int = 200,
        flush_interval_sec: float = 1.0,
        queue_maxsize: int = 10_000,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.engine = engine
        self.service_name = service_name
        self.loop = loop
        self.batch_size = max(1, batch_size)
        self.flush_interval_sec = max(0.05, flush_interval_sec)
        self.queue: "asyncio.Queue[Dict[str, Any] | object]" = asyncio.Queue(
            maxsize=queue_maxsize
        )
        self.on_error = on_error

        self._closed = False

        self._session_factory = async_sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )

        self._worker_task = self.loop.create_task(self._run())

        from src.models.db_log import LogRecord
        self._LogEntryModel = LogRecord

    def __call__(self, message):
        record = message.record
        extra = record["extra"] or {}

        payload = {
            "level": record["level"].name,
            "service_name": self.service_name,
            "message": record["message"],
            "exception_traceback": extra.get("traceback_str"),
            "logger_name": record["name"],
            "module": record["module"],
            "function": record["function"],
            "line": record["line"],
            "user_id": extra.get("user_id"),
            "task_id": extra.get("task_id"),
            "created_at": record["time"],
        }

        if self._closed:
            self._warn("[BatchedDBSink] sink is closed, dropping log record")
            return

        try:
            asyncio.run_coroutine_threadsafe(
                self.queue.put(payload),
                self.loop,
            )
        except Exception as e:
            self._warn(f"[BatchedDBSink] failed to enqueue log record: {e!r}")

    async def close(self):
        """
        Грациозное завершение:
        - помечаем как закрытый
        - кладём SENTINEL в очередь, чтобы _run увидел конец
        - ждём завершения worker-таски
        """
        if self._closed:
            return

        self._closed = True
        try:
            await self.queue.put(_SENTINEL)
        except Exception:
            pass

        try:
            await asyncio.wait_for(self._worker_task, timeout=10.0)
        except asyncio.TimeoutError:
            self._warn("[BatchedDBSink] worker did not stop in time")

    def _warn(self, msg: str):
        if self.on_error:
            try:
                self.on_error(msg)
                return
            except Exception:
                pass

        print(msg, file=sys.stderr)

    async def _run(self):
        """
        Основной воркер:
        - забирает записи из очереди
        - собирает их в батчи
        - по размеру/таймауту пишет в БД
        - при получении SENTINEL дочищает и завершает работу
        """
        batch: List[Dict[str, Any]] = []
        last_flush = self.loop.time()

        while True:
            try:
                item = await asyncio.wait_for(
                    self.queue.get(),
                    timeout=self.flush_interval_sec,
                )
            except asyncio.TimeoutError:
                item = None

            if item is _SENTINEL:
                if batch:
                    await self._flush_batch(batch)
                break

            if item is not None:
                batch.append(item)  # type: ignore[arg-type]

            now = self.loop.time()
            should_flush = (
                len(batch) >= self.batch_size
                or (batch and (now - last_flush) >= self.flush_interval_sec)
            )

            if should_flush:
                await self._flush_batch(batch)
                batch = []
                last_flush = now

        if batch:
            await self._flush_batch(batch)

    async def _flush_batch(self, batch: List[Dict[str, Any]]):
        if not batch:
            return

        rows = [
            dict(
                level=b["level"],
                service_name=b["service_name"],
                message=b["message"],
                exception_traceback=b.get("exception_traceback"),
                logger_name=b["logger_name"],
                module=b["module"],
                function=b["function"],
                line=b["line"],
                user_id=b.get("user_id"),
                task_id=b.get("task_id"),
                created_at=b.get("created_at"),
            )
            for b in batch
        ]

        try:
            async with self._session_factory() as session:
                await session.execute(insert(self._LogEntryModel), rows)
                await session.commit()

        except Exception as e:
            self._warn(f"[BatchedDBSink] DB write failed, dropping batch: {e}")


DB_SINK: BatchedDBSink | None = None
DB_SINK_HANDLER_ID: int | None = None


def add_db_log_sink(
    loop: asyncio.AbstractEventLoop,
    level: str = "INFO",
    *,
    engine: AsyncEngine,
    service_name: Optional[str] = None,
):
    """
    Регистрирует асинхронный батчевый sink в Loguru.
    Аналогично add_websocket_log_sink.
    """
    global DB_SINK, DB_SINK_HANDLER_ID

    DB_SINK = BatchedDBSink(
        engine=engine,
        service_name=service_name or config.COMMON.SERVICE_NAME,
        loop=loop,
        batch_size=config.LOGGING.LOG_BATCH_SIZE,
        flush_interval_sec=config.LOGGING.LOG_FLUSH_INTERVAL_SEC,
        queue_maxsize=config.LOGGING.LOG_QUEUE_MAXSIZE,
    )

    DB_SINK_HANDLER_ID = loguru_logger.add(
        DB_SINK,
        level=level.upper(),
        enqueue=True,
        catch=True,
        format=sink_formatter,
    )

    loguru_logger.info(
        f"Structured DB log sink added with level {level.upper()} (async, no WAL)."
    )
