from __future__ import annotations

import asyncio

import pytest

from src.clients.base.grpc import BaseGrpcClient


class _NeverReadyChannel:
    async def channel_ready(self) -> None:
        await asyncio.Event().wait()


class _TestGrpcClient(BaseGrpcClient[object]):
    def _create_stub(self, channel) -> object:
        return object()


@pytest.mark.asyncio
async def test_wait_channel_ready_is_bounded_by_client_timeout() -> None:
    client = _TestGrpcClient(
        "unused",
        channel=_NeverReadyChannel(),
        timeout_seconds=0.05,
        wait_ready_initial=0.01,
        wait_ready_max=0.02,
        reconnect_max_delay=0.01,
    )

    loop = asyncio.get_running_loop()
    started_at = loop.time()

    with pytest.raises(TimeoutError, match=r"channel did not become READY within 0\.05s"):
        await client.wait_channel_ready()

    assert loop.time() - started_at < 0.2
