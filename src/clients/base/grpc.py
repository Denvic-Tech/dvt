from __future__ import annotations

import asyncio
import contextlib
import random
from abc import ABC, abstractmethod
from typing import Any, Generic, Iterable, Optional, Sequence, Tuple, TypeVar

import grpc
from loguru import logger

StubT = TypeVar("StubT")
ChannelOption = Tuple[str, Any]
MetadataEntry = Tuple[str, str]


class BaseGrpcClient(Generic[StubT], ABC):
    """
    Универсальный асинхронный gRPC клиент с общим управлением каналом:
      * настройка secure/insecure каналов + кастомные options;
      * формирование metadata (auth + пользовательские заголовки);
      * ожидание готовности канала, реконнекты с экспоненциальным backoff;
      * шаблонные хуки для открытия/закрытия стримов и расширяемое поведение.

    Классы-наследники реализуют `_create_stub()` и при необходимости переопределяют
    `_default_channel_options()`, `_extra_metadata()`, `_post_connect()` и др.
    """

    def __init__(
        self,
        target: str,
        *,
        token: Optional[str] = None,
        token_header: str = "authorization",
        secure: bool = False,
        ssl_credentials: Optional[grpc.ChannelCredentials] = None,
        channel: Optional[grpc.aio.Channel] = None,
        channel_options: Optional[Iterable[ChannelOption]] = None,
        max_attempts: Optional[int] = 5,
        timeout_seconds: float = 60.0,
        wait_ready_initial: float = 2.0,
        wait_ready_max: float = 15.0,
        reconnect_min_delay: float = 0.25,
        reconnect_max_delay: float = 5.0,
        reconnect_jitter: float = 0.1,
    ) -> None:
        self._target = target
        self._token = token
        self._token_header = token_header

        self._secure = secure
        self._ssl_credentials = ssl_credentials
        self._timeout_seconds = timeout_seconds

        self._explicit_channel_options = tuple(channel_options) if channel_options is not None else None
        self._channel_owner = channel is None
        self._channel: Optional[grpc.aio.Channel] = channel
        self._stub: Optional[StubT] = None

        self._name = self.__class__.__name__

        self._max_attempts = max_attempts
        self._ready_first_timeout = wait_ready_initial
        self._ready_max_timeout = wait_ready_max
        self._reconnect_min_delay = reconnect_min_delay
        self._reconnect_max_delay = reconnect_max_delay
        self._reconnect_jitter = reconnect_jitter

    # ------------------------------------------------------------------ #
    #                           Metadata helpers                         #
    # ------------------------------------------------------------------ #

    def metadata(self) -> tuple[MetadataEntry, ...]:
        """
        Возвращает базовый набор metadata для RPC-вызовов.
        """
        entries: list[MetadataEntry] = []
        entries.extend(self._token_metadata())
        entries.extend(self._extra_metadata())
        return tuple(entries)

    def _token_metadata(self) -> Sequence[MetadataEntry]:
        if self._token and self._token_header:
            return ((self._token_header, self._token),)
        return ()

    def _extra_metadata(self) -> Sequence[MetadataEntry]:
        """
        Шаблонный метод: потомки могут добавить дополнительные пары.
        """
        return ()

    # ------------------------------------------------------------------ #
    #                Channel lifecycle / connect / reconnect             #
    # ------------------------------------------------------------------ #

    async def __aenter__(self) -> "BaseGrpcClient[StubT]":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def connect(
        self,
        *,
        wait_ready: bool = False,
        first_timeout: Optional[float] = None,
        max_timeout: Optional[float] = None,
    ) -> StubT:
        """
        Создаёт канал/стаб (при необходимости) и опционально ждёт READY.
        """
        stub = self._ensure_stub()
        if wait_ready:
            await self.wait_channel_ready(first_timeout=first_timeout, max_timeout=max_timeout)
        await self._post_connect()
        return stub

    async def reconnect(
        self,
        *,
        wait_ready: bool = True,
        first_timeout: Optional[float] = None,
        max_timeout: Optional[float] = None,
    ) -> StubT:
        """
        Переоткрывает канал с экспоненциальным backoff до успешного соединения.
        """
        delay = self._reconnect_min_delay
        attempt = 0
        while not self._should_stop():
            attempt += 1

            if attempt > self._max_attempts:
                raise RuntimeError(f"[{self._name}] reconnect aborted by stop condition")

            try:
                await self._before_reconnect_attempt(attempt)
                await self._close_channel()

                stub = self._ensure_stub()
                if wait_ready:
                    await self.wait_channel_ready(first_timeout=first_timeout, max_timeout=max_timeout)

                await self._post_connect()
                logger.info(f"[{self._name}] reconnect successful (attempt={attempt})")
                return stub

            except Exception as exc:  # pragma: no cover - защитный лог
                await self._on_reconnect_error(exc, attempt, delay)
                await self._sleep_backoff(delay)
                delay = min(delay * 2, self._reconnect_max_delay)

        raise RuntimeError(f"[{self._name}] reconnect aborted by stop condition")

    async def wait_channel_ready(
        self,
        *,
        first_timeout: Optional[float] = None,
        max_timeout: Optional[float] = None,
    ) -> None:
        """Wait until the channel is READY, bounded by the client timeout."""
        if self._channel is None:
            return

        timeout = self._ready_first_timeout if first_timeout is None else first_timeout
        timeout_max = self._ready_max_timeout if max_timeout is None else max_timeout
        timeout = max(0.0, float(timeout))
        timeout_max = max(timeout, float(timeout_max))
        total_timeout = max(0.0, float(self._timeout_seconds))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + total_timeout
        attempt = 0

        while not self._should_stop():
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"[{self._name}] channel did not become READY within {total_timeout:.2f}s"
                )

            attempt_timeout = min(timeout, remaining)
            try:
                await asyncio.wait_for(
                    self._channel.channel_ready(),
                    timeout=attempt_timeout,
                )
                return
            except (TimeoutError, grpc.aio.AioRpcError) as exc:
                attempt += 1
                logger.debug(
                    f"[{self._name}] waiting for READY "
                    f"(attempt={attempt}, timeout={attempt_timeout:.2f}s): {exc}"
                )
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError(
                        f"[{self._name}] channel did not become READY within "
                        f"{total_timeout:.2f}s"
                    ) from exc

                sleep_time = min(timeout, self._reconnect_max_delay, remaining)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                timeout = min(timeout_max, timeout * 1.7)

        raise RuntimeError(f"[{self._name}] wait_channel_ready aborted by stop condition")

    async def close(self) -> None:
        """
        Закрывает канал, если он принадлежит клиенту, и сбрасывает стабы.
        """
        await self._close_channel()

    # ------------------------------------------------------------------ #
    #                          Internal helpers                          #
    # ------------------------------------------------------------------ #

    def _ensure_stub(self) -> StubT:
        """
        Гарантирует, что стаба и канал созданы. Канал создаётся lazily.
        """
        if self._channel is None:
            self._channel = self._make_channel()
            self._channel_owner = True
            self._channel_created(self._channel)

        if self._stub is None:
            self._stub = self._create_stub(self._channel)

        return self._stub

    def _reset_stub(self) -> None:
        """
        Используется потомками для принудительного пересоздания стаба.
        """
        self._stub = None

    async def _close_channel(self) -> None:
        if self._channel is None:
            return

        await self._before_channel_close()

        if self._channel_owner:
            with contextlib.suppress(Exception):
                await self._channel.close()
            logger.debug(f"[{self._name}] closed owned channel")

        self._channel = None
        self._reset_stub()
        self._channel_owner = True

    def _make_channel(self) -> grpc.aio.Channel:
        options = self._resolve_channel_options()
        if self._secure:
            creds = self._ssl_credentials or grpc.ssl_channel_credentials()
            return grpc.aio.secure_channel(self._target, creds, options=options)
        return grpc.aio.insecure_channel(self._target, options=options)

    def _channel_created(self, channel: grpc.aio.Channel) -> None:
        """
        Хук для потомков. По умолчанию только логируем создание канала.
        """
        logger.debug(f"[{self._name}] created channel → {self._target}")

    def _resolve_channel_options(self) -> tuple[ChannelOption, ...]:
        if self._explicit_channel_options is not None:
            return tuple(self._explicit_channel_options)
        return tuple(self._default_channel_options())

    def _default_channel_options(self) -> Iterable[ChannelOption]:
        """
        Потомки могут вернуть набор options по умолчанию.
        """
        return ()

    async def _sleep_backoff(self, delay: float) -> None:
        """
        Засыпает с небольшим джиттером для равномерного распределения реконнектов.
        """
        jitter = random.random() * self._reconnect_jitter
        await asyncio.sleep(delay + jitter)

    # ------------------------------------------------------------------ #
    #                       Overridable extension hooks                  #
    # ------------------------------------------------------------------ #

    def _should_stop(self) -> bool:
        """
        Потомки могут сигнализировать о завершении (например, когда клиент закрывается).
        """
        return False

    async def _post_connect(self) -> None:
        """
        Хук после успешного создания канала/стаба (например, открыть стрим).
        """
        return None

    async def _before_channel_close(self) -> None:
        """
        Хук перед закрытием канала (например, корректно закрыть активные стримы).
        """
        return None

    async def _before_reconnect_attempt(self, attempt: int) -> None:
        """
        Хук перед очередной попыткой реконнекта (например, сбросить метрики).
        """
        return None

    async def _on_reconnect_error(self, exc: Exception, attempt: int, delay: float) -> None:
        """
        Хук при ошибке реконнекта: по умолчанию логируем предупреждение.
        """
        logger.warning(
            f"[{self._name}] reconnect failed (attempt={attempt}, next_delay={delay:.2f}s): {type(exc).__name__}: {exc}"
        )

    # ------------------------------------------------------------------ #
    #                         Abstract contract                          #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def _create_stub(self, channel: grpc.aio.Channel) -> StubT:
        """
        Фабрика стаба конкретного gRPC сервиса.
        """
