from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from redis import asyncio as redis

pytestmark = pytest.mark.docker_required


def _redis_url(redis_container) -> str:
    return (
        f"redis://{redis_container.get_container_host_ip()}:"
        f"{redis_container.get_exposed_port(6379)}/0"
    )


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("kind", ["commands", "events"])
async def test_stale_pending_stream_entry_is_reclaimed_and_acked(redis_container, kind: str):
    client = redis.from_url(_redis_url(redis_container), decode_responses=True)
    stream = f"test:orchestrator:{kind}:{uuid4().hex}"
    group = f"group-{uuid4().hex}"
    try:
        await client.xgroup_create(stream, group, id="0-0", mkstream=True)
        message_id = await client.xadd(stream, {"payload": '{"value":"test"}'})

        first = await client.xreadgroup(group, "consumer-a", {stream: ">"}, count=1)
        assert first[0][1][0][0] == message_id

        # consumer-a disappears without XACK; consumer-b must recover the PEL entry.
        await asyncio.sleep(0.02)
        claimed = await client.xautoclaim(
            stream,
            group,
            "consumer-b",
            min_idle_time=1,
            start_id="0-0",
            count=10,
        )
        claimed_messages = claimed[1]
        assert [item[0] for item in claimed_messages] == [message_id]

        assert await client.xack(stream, group, message_id) == 1
        pending = await client.xpending(stream, group)
        assert pending["pending"] == 0
    finally:
        await client.delete(stream)
        await client.aclose()
