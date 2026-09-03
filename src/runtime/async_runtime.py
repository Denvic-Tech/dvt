from __future__ import annotations

import asyncio
import atexit
from inspect import iscoroutinefunction
from types import TracebackType
from typing import Any, Awaitable, Callable, Generic, Optional, Protocol, Self, Type, TypeVar, runtime_checkable

import grpc

from src.clients.ws_forward_client import WSForwardClient
from src.clients.orchestrator_client import GrpcOrchestratorClient
from src.runtime.async_loop_worker import AsyncLoopWorker
from src.runtime.grpc_channel import GRPCChannelManager, default_channel_options
import config


def _proactor_dask_tokenize(self):
    return (self.__class__.__name__, id(self))


if hasattr(asyncio, "ProactorEventLoop"):
    asyncio.ProactorEventLoop.__dask_tokenize__ = _proactor_dask_tokenize


@runtime_checkable
class AsyncClientProtocol(Protocol):
    async def __aenter__(self) -> Self:
        ...

    async def __aexit__(
            self,
            exc_type: Optional[type[BaseException]],
            exc: Optional[BaseException],
            tb: Optional[TracebackType],
    ) -> None:
        ...


ClientT = TypeVar("ClientT")
ChannelFactory = Callable[[], Awaitable[grpc.aio.Channel]]


class SharedGrpcClient(Generic[ClientT]):
    """
    Универсальный адаптер, который держит один экземпляр gRPC-клиента, открытый в отдельном event loop.
    Поддерживает любые клиентов, реализующих асинхронный контекстный менеджер.
    """

    def __init__(
            self,
            client_cls: Type[ClientT],
            *client_args: Any,
            channel_factory: ChannelFactory | None = None,
            **client_kwargs: Any,
    ) -> None:
        if not isinstance(client_cls, type):
            raise TypeError("client_cls must be a class type")
        if not issubclass(client_cls, AsyncClientProtocol):
            raise TypeError("client_cls must implement async context manager protocol")

        enter = getattr(client_cls, "__aenter__", None)
        exit_ = getattr(client_cls, "__aexit__", None)
        if not (enter and iscoroutinefunction(enter)):
            raise TypeError(f"{client_cls.__name__}.__aenter__ must be defined as an async method")
        if not (exit_ and iscoroutinefunction(exit_)):
            raise TypeError(f"{client_cls.__name__}.__aexit__ must be defined as an async method")

        self._client_cls: Type[ClientT] = client_cls
        self._client_args: tuple[Any, ...] = client_args
        self._client_kwargs: dict[str, Any] = client_kwargs

        self._context_manager: Optional[ClientT] = None
        self._client: Optional[ClientT] = None
        self._lock: Optional[asyncio.Lock] = None
        self._channel_factory: ChannelFactory | None = channel_factory
        self._channel: Optional[grpc.aio.Channel] = None

    async def get(self) -> ClientT:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._client is None:
                kwargs = dict(self._client_kwargs)
                if self._channel_factory is not None:
                    kwargs["channel"] = await self._ensure_channel()
                context_manager = self._client_cls(*self._client_args, **kwargs)
                client = await context_manager.__aenter__()
                self._context_manager = context_manager
                self._client = client
            return self._client

    async def close(self) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._context_manager is not None:
                await self._context_manager.__aexit__(None, None, None)
                self._context_manager = None
                self._client = None
                if self._channel_factory is not None:
                    self._channel = None

    async def _ensure_channel(self) -> grpc.aio.Channel:
        if self._channel_factory is None:
            raise RuntimeError("Channel factory is not configured for this SharedGrpcClient instance.")

        if self._channel is not None:
            return self._channel

        self._channel = await self._channel_factory()
        return self._channel


async_worker = AsyncLoopWorker()

ws_forward_grpc_channel_manager = GRPCChannelManager(
    config.WS_FORWARD.GRPC_FORWARD_SERVICE_URL,
    "ws_forward.v1.ForwardWS",
    max_send_message_length=config.WS_FORWARD.GRPC_FORWARD_SERVICE_MAX_SEND_MESSAGE_LEN_MB * 1024 * 1024,
    max_receive_message_length=config.WS_FORWARD.GRPC_FORWARD_SERVICE_MAX_RECEIVE_MESSAGE_LEN_MB * 1024 * 1024,
)

orchestrator_grpc_channel_manager = GRPCChannelManager(
    config.ORCHESTRATOR.ORCHESTRATOR_URL,
    "orchestrator.v1.Orchestrator"
)

shared_ws_forward = SharedGrpcClient(
    WSForwardClient,
    channel_factory=ws_forward_grpc_channel_manager.get_channel,
    target=config.WS_FORWARD.GRPC_FORWARD_SERVICE_URL,
    token=config.WS_FORWARD.GRPC_FORWARD_SERVICE_TOKEN,
)

shared_orchestrator = SharedGrpcClient(
    GrpcOrchestratorClient,
channel_factory=orchestrator_grpc_channel_manager.get_channel,
    target=config.ORCHESTRATOR.ORCHESTRATOR_URL,
    token=config.ORCHESTRATOR.ORCHESTRATOR_TOKEN
)

async def _close_shared_clients() -> None:
    await shared_ws_forward.close()
    await ws_forward_grpc_channel_manager.close_channel()


def _shutdown() -> None:
    try:
        async_worker.ensure_own_loop()
        async_worker.run(_close_shared_clients())
    except RuntimeError:
        # Event loop мог быть остановлен до завершения очистки.
        pass
    finally:
        if async_worker.owns_loop:
            async_worker.stop()


atexit.register(_shutdown)
