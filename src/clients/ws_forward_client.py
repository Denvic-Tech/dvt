import time
import asyncio
import contextlib
from typing import Iterable, Optional, Tuple, List, TYPE_CHECKING

import grpc

from contracts.src.ws_forward.v1 import forward_pb2, forward_pb2_grpc

from src.clients.base.grpc import BaseGrpcClient, ChannelOption
from src.logger import logger

if TYPE_CHECKING:
    from src.schemas.event import Event


_DEFAULT_CHANNEL_OPTIONS: list[Tuple[str, int]] = [
    ("grpc.enable_http_proxy", 0),
    ("grpc.keepalive_time_ms", 300_000),
    ("grpc.keepalive_timeout_ms", 20_000),
    ("grpc.keepalive_permit_without_calls", 0),
    ("grpc.http2.max_pings_without_data", 1),
    ("grpc.http2.min_time_between_pings_ms", 120_000),
    ("grpc.http2.min_ping_interval_without_data_ms", 300_000),
]


class WSForwardClient(BaseGrpcClient[forward_pb2_grpc.ForwardWSStub]):
    """
    Клиент для надёжной отправки множества ForwardRequest через один client-stream.

    Модель: многие продьюсеры кладут сообщения в asyncio.Queue,
    один фоновой воркер последовательно пишет в gRPC-стрим, сам делает реконнект и ретраи.

    Семантика доставки: best-effort (логи). При реконнектах текущая пачка ретраится целиком.
    Чтобы не раздувать память, предусмотрены политики переполнения и ограничение размера пачки.

    Публичный API совместим с прежним клиентом: вызывает client(message, user_id, project_id).
    """

    def __init__(
        self,
        target: str,
        *,
        token: Optional[str] = None,
        secure: bool = False,
        ssl_credentials: Optional[grpc.ChannelCredentials] = None,

        channel: Optional[grpc.aio.Channel] = None,
        channel_options: Optional[Iterable[Tuple[str, int]]] = None,
        timeout_seconds: float = 60.0,

        queue_maxsize: int = 10_000,
        overflow_policy: str = "drop_oldest",

        batch_max: int = 256,
        batch_max_bytes: int = 1024 * 1024,      # ~0.5MB на одну отправку
        batch_max_delay: float = 0.02,           # не дольше 20мс ждём добора пачки

        reconnect_min_delay: float = 0.25,
        reconnect_max_delay: float = 5.0,

        max_consecutive_errors: int = 50,
    ):
        super().__init__(
            target=target,
            token=token,
            token_header="x-api-key",
            secure=secure,
            ssl_credentials=ssl_credentials,
            channel=channel,
            timeout_seconds=timeout_seconds,
            wait_ready_initial=2.0,
            wait_ready_max=15.0,
            reconnect_min_delay=reconnect_min_delay,
            reconnect_max_delay=reconnect_max_delay,
        )

        self._channel_options_base: tuple[ChannelOption, ...] = tuple(channel_options or _DEFAULT_CHANNEL_OPTIONS)

        self._queue: asyncio.Queue[forward_pb2.ForwardRequest] = asyncio.Queue(maxsize=queue_maxsize)
        self._overflow_policy = overflow_policy

        self._batch_max = max(1, batch_max)
        self._batch_max_bytes = max(4 * 1024, batch_max_bytes)
        self._batch_max_delay = max(0.0, batch_max_delay)

        self._reconnect_min = reconnect_min_delay
        self._reconnect_max = reconnect_max_delay
        self._max_consecutive_errors = max(1, max_consecutive_errors)

        self._stream: Optional[grpc.aio.StreamStreamCall] = None

        self._writer_task: Optional[asyncio.Task] = None
        self._closed = False

        self._enqueued = 0
        self._sent = 0
        self._dropped = 0
        self._reconnects = 0
        self._retries = 0

    # ---------------------- Base client hooks ----------------------

    def _default_channel_options(self) -> Iterable[ChannelOption]:
        reconnect_opts: list[ChannelOption] = [
            ("grpc.initial_reconnect_backoff_ms", int(self._reconnect_min * 1000)),
            ("grpc.min_reconnect_backoff_ms", int(self._reconnect_min * 1000)),
            ("grpc.max_reconnect_backoff_ms", int(self._reconnect_max * 1000)),
        ]
        return tuple(self._channel_options_base + tuple(reconnect_opts))

    def _create_stub(self, channel: grpc.aio.Channel) -> forward_pb2_grpc.ForwardWSStub:
        return forward_pb2_grpc.ForwardWSStub(channel)

    async def _post_connect(self) -> None:
        if self._stream is None:
            stub = self._ensure_stub()
            self._stream = stub.ForwardStream(metadata=self.metadata())
            action = "stream re-created" if self._reconnects else "stream opened"
            logger.info(f"[{self._name}] {action} → {self._target}")

    async def _before_channel_close(self) -> None:
        if self._stream is not None:
            with contextlib.suppress(Exception):
                await self._stream.done_writing()
            self._stream = None

    def _should_stop(self) -> bool:
        return self._closed

    async def reconnect(
        self,
        *,
        wait_ready: bool = True,
        first_timeout: Optional[float] = None,
        max_timeout: Optional[float] = None,
    ) -> forward_pb2_grpc.ForwardWSStub:
        self._reconnects += 1
        return await super().reconnect(wait_ready=wait_ready, first_timeout=first_timeout, max_timeout=max_timeout)

    async def _ensure_stream(self, *, wait_ready: bool = True) -> grpc.aio.StreamStreamCall:
        if self._stream is None:
            await self.connect(wait_ready=wait_ready)
        if self._stream is None:
            raise RuntimeError(f"[{self._name}] stream is not initialized")
        return self._stream

    # ---------------------- Жизненный цикл ----------------------

    async def start(self) -> None:
        if self._writer_task is not None:
            return

        self._closed = False
        await self._ensure_stream(wait_ready=True)
        self._writer_task = asyncio.create_task(self._writer_loop(), name=f"{self._name}-writer")
        logger.info(f"[{self._name}] started → {self._target}")

    async def close(self, *, drain: bool = True, drain_timeout: float = 2.0) -> None:
        self._closed = True
        if drain and self._writer_task is not None:
            try:
                await asyncio.wait_for(self._queue.join(), timeout=drain_timeout)
            except asyncio.TimeoutError:
                pass

        if self._writer_task is not None:
            self._writer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._writer_task

            self._writer_task = None

        await super().close()

        logger.info(f"[{self._name}] closed (sent={self._sent}, dropped={self._dropped}, enq={self._enqueued})")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    # ---------------------- Публичный API ----------------------

    async def __call__(
        self,
        message: "Event",
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        *,
        timeout: float | None = None,
    ) -> None:
        if not user_id or not project_id or self._closed:
            return

        req = self._to_request(message, user_id, project_id)
        await self._enqueue(req)

    async def send_message(
            self,
            message: "Event",
            user_id: Optional[str] = None,
            project_id: Optional[str] = None,
    ):
        if not user_id or not project_id or self._closed:
            return

        req = self._to_request(message, user_id, project_id)
        await self._enqueue(req)

    # ---------------------- Внутреннее ----------------------

    def _to_request(
            self,
            message: "Event",
            user_id: str,
            project_id: str
    ) -> forward_pb2.ForwardRequest:
        payload = message.model_dump_json()
        timestamp = str(getattr(message, "timestamp", ""))
        task_id = getattr(message, "task_id", "")
        node_id = getattr(message, "node_id", "")

        return forward_pb2.ForwardRequest(
            user_id=user_id,
            project_id=project_id,
            type=message.type,
            task_id=task_id,
            node_id=node_id,
            payload_json=payload,
            ts=timestamp,
        )

    async def _enqueue(self, req: forward_pb2.ForwardRequest) -> None:
        if self._overflow_policy == "block":
            await self._queue.put(req)
            self._enqueued += 1
            return

        if self._queue.full():
            if self._overflow_policy == "drop_oldest":
                with contextlib.suppress(asyncio.QueueEmpty):
                    dropped = self._queue.get_nowait()
                    self._queue.task_done()
                    self._dropped += 1
                    logger.warning(f"[{self._name}] dropped message due to queue overflow: {dropped.type}")

                with contextlib.suppress(asyncio.QueueFull):
                    self._queue.put_nowait(req)
                    self._enqueued += 1

                return

            else:
                self._dropped += 1
                return
        else:
            with contextlib.suppress(asyncio.QueueFull):
                self._queue.put_nowait(req)
                self._enqueued += 1

    # --------------- Воркер записи: собирает батчи и пишет ---------------

    async def _writer_loop(self) -> None:
        consecutive_errors = 0
        try:
            while True:
                if self._closed and self._queue.empty():
                    break
                # Гарантируем наличие активного стрима
                stream = await self._ensure_stream(wait_ready=True)

                # Пакуем батч
                batch, total_bytes = await self._collect_batch()
                if not batch:
                    continue

                # Пишем пачку
                try:
                    for req in batch:
                        await stream.write(req)
                        self._sent += 1
                    consecutive_errors = 0

                    # Сообщаем очереди, что задачи обработаны
                    for _ in batch:
                        self._queue.task_done()

                except grpc.aio.AioRpcError as e:
                    consecutive_errors += 1
                    logger.warning(
                        f"[{self._name}] write failed ({e.code()}): {e}; reconnecting… "
                        f"(batch={len(batch)}, bytes={total_bytes})"
                    )
                    await self.reconnect()
                    try:
                        stream = await self._ensure_stream(wait_ready=True)
                        for req in batch:
                            await stream.write(req)
                            self._sent += 1

                        for _ in batch:
                            self._queue.task_done()

                        self._retries += len(batch)
                        consecutive_errors = 0

                    except Exception as e2:
                        logger.error(
                            f"[{self._name}] retry after reconnect failed: {type(e2)}: {e2}; "
                            f"dropping {len(batch)} msgs"
                        )
                        for _ in batch:
                            self._queue.task_done()

                except RuntimeError as e:
                    consecutive_errors += 1
                    emsg = str(e).lower()

                    if _is_stream_finished_error(e):
                        logger.warning(
                            f"[{self._name}] runtime write failed (stream finished): {e}; "
                            f"reconnecting… (batch={len(batch)}, bytes={total_bytes})"
                        )
                        await self.reconnect()

                        try:
                            stream = await self._ensure_stream(wait_ready=True)
                            for req in batch:
                                await stream.write(req)
                                self._sent += 1

                            for _ in batch:
                                self._queue.task_done()

                            self._retries += len(batch)
                            consecutive_errors = 0

                        except Exception as e2:
                            logger.error(
                                f"[{self._name}] retry after reconnect failed: {type(e2)}: {e2}; "
                                f"dropping {len(batch)} msgs"
                            )
                            for _ in batch:
                                self._queue.task_done()
                    else:
                        logger.error(
                            f"[{self._name}] unexpected runtime error: {e}; "
                            f"dropping {len(batch)} msgs"
                        )
                        for _ in batch:
                            self._queue.task_done()

                except Exception as e:
                    consecutive_errors += 1

                    if _is_stream_finished_error(e):
                        logger.warning(
                            f"[{self._name}] write failed (unexpected type={type(e)} stream finished): {e}; "
                            f"reconnecting… (batch={len(batch)}, bytes={total_bytes})"
                        )
                        await self.reconnect()
                        try:
                            stream = await self._ensure_stream(wait_ready=True)
                            for req in batch:
                                await stream.write(req)
                                self._sent += 1

                            for _ in batch:
                                self._queue.task_done()

                            self._retries += len(batch)
                            consecutive_errors = 0

                        except Exception as e2:
                            logger.error(
                                f"[{self._name}] retry after reconnect failed: {type(e2)}: {e2}; "
                                f"dropping {len(batch)} msgs"
                            )
                            for _ in batch:
                                self._queue.task_done()
                    else:
                        logger.error(
                            f"[{self._name}] unexpected write error: {type(e)}: {e}; "
                            f"dropping {len(batch)} msgs"
                        )
                        for _ in batch:
                            self._queue.task_done()

                if consecutive_errors >= self._max_consecutive_errors:
                    await asyncio.sleep(min(self._reconnect_max, 1.0))
                    consecutive_errors = 0

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception(f"[{self._name}] writer loop crashed: {e}")

    async def _collect_batch(self) -> Tuple[List[forward_pb2.ForwardRequest], int]:
        batch: List[forward_pb2.ForwardRequest] = []
        total_bytes = 0

        try:
            req = await asyncio.wait_for(self._queue.get(), timeout=self._batch_max_delay)
        except asyncio.TimeoutError:
            return batch, 0

        batch.append(req)
        total_bytes += _approx_size(req)
        deadline = time.perf_counter() + self._batch_max_delay

        while len(batch) < self._batch_max and total_bytes < self._batch_max_bytes:
            if time.perf_counter() >= deadline:
                break
            try:
                req2 = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            size2 = _approx_size(req2)
            if total_bytes + size2 > self._batch_max_bytes:
                with contextlib.suppress(asyncio.QueueFull):
                    self._queue.put_nowait(req2)

                break
            batch.append(req2)
            total_bytes += size2

        return batch, total_bytes

    # ---------------------- Метрики ----------------------

    def stats(self) -> dict:
        return {
            "enqueued": self._enqueued,
            "sent": self._sent,
            "dropped": self._dropped,
            "retries": self._retries,
            "reconnects": self._reconnects,
            "queue_size": self._queue.qsize(),
        }


# ------------------------ Утилиты ------------------------


def _approx_size(req: forward_pb2.ForwardRequest) -> int:
    return (
        len(req.user_id)
        + len(req.project_id)
        + len(req.type)
        + len(req.task_id)
        + len(req.node_id)
        + len(req.payload_json)
        + len(req.ts)
        + 64
    )


def _is_stream_finished_error(e: Exception) -> bool:
    """
    На некоторых версиях gRPC ошибка "RPC already finished." может лететь не как RuntimeError,
    а как другой Exception. Мы смотрим по тексту, а не по типу.
    """
    emsg = str(e).lower()
    return "rpc already finished" in emsg or "stream closed" in emsg
