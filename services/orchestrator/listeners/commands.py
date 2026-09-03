import asyncio
import contextlib

import orjson
from redis import asyncio as redis
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    ResponseError,
    TimeoutError as RedisTimeoutError,
)

from services.orchestrator.deps.commands import handle_nested_task_enqueue

from src.logger import logger
from src.modules.task_execution.infra.transport import NestedTaskEnqueueCommand, OrchestratorCommand

import config

RECONNECT_DELAY_SEC = 1.0


class CommandsStreamListener:
    def __init__(self) -> None:
        self._redis: redis.Redis | None = None
        self._task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._group_ready = False

    def _create_redis(self) -> redis.Redis:
        return redis.Redis(
            host=config.VALKEY.VALKEY_HOST,
            port=config.VALKEY.VALKEY_PORT,
            password=config.VALKEY.VALKEY_PASSWORD,
            decode_responses=True,
        )

    async def start(self) -> None:
        if self._task:
            return
        self._shutdown_event.clear()
        self._task = asyncio.create_task(self._listen(), name="orchestrator-commands-listener")

    async def stop(self) -> None:
        self._shutdown_event.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._disconnect()

    async def _ensure_group(self) -> None:
        assert self._redis is not None
        try:
            await self._redis.xgroup_create(
                name=config.ORCHESTRATOR.ORCH_COMMANDS_STREAM,
                groupname=config.ORCHESTRATOR.ORCH_COMMANDS_GROUP,
                id="0-0",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _ensure_ready(self) -> None:
        if self._redis is None:
            self._redis = self._create_redis()
            self._group_ready = False

        if not self._group_ready:
            await self._ensure_group()
            self._group_ready = True

    async def _disconnect(self) -> None:
        client = self._redis
        self._redis = None
        self._group_ready = False
        if client is not None:
            with contextlib.suppress(Exception):
                await client.close()

    async def _wait_before_retry(self) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=RECONNECT_DELAY_SEC)

    async def _handle_command(self, command: OrchestratorCommand) -> None:
        if isinstance(command, NestedTaskEnqueueCommand):
            await handle_nested_task_enqueue(command)
            return
        logger.warning("Unhandled orchestrator command", command_type=type(command))

    async def _listen(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                await self._ensure_ready()
                assert self._redis is not None

                claimed = await self._redis.xautoclaim(
                    name=config.ORCHESTRATOR.ORCH_COMMANDS_STREAM,
                    groupname=config.ORCHESTRATOR.ORCH_COMMANDS_GROUP,
                    consumername=config.ORCHESTRATOR.ORCH_COMMANDS_CONSUMER,
                    min_idle_time=int(config.ORCHESTRATOR.ORCH_STREAM_PENDING_IDLE_SEC * 1000),
                    start_id="0-0",
                    count=config.ORCHESTRATOR.ORCH_COMMANDS_BATCH_SIZE,
                )
                claimed_messages = claimed[1]
                entries = await self._redis.xreadgroup(
                    groupname=config.ORCHESTRATOR.ORCH_COMMANDS_GROUP,
                    consumername=config.ORCHESTRATOR.ORCH_COMMANDS_CONSUMER,
                    streams={config.ORCHESTRATOR.ORCH_COMMANDS_STREAM: ">"},
                    count=config.ORCHESTRATOR.ORCH_COMMANDS_BATCH_SIZE,
                    block=config.ORCHESTRATOR.ORCH_COMMANDS_BLOCK_MS,
                )

                batches = [(config.ORCHESTRATOR.ORCH_COMMANDS_STREAM, claimed_messages)]
                batches.extend(entries)
                for _stream, messages in batches:
                    for message_id, fields in messages:
                        try:
                            payload = fields.get("payload")
                            command = NestedTaskEnqueueCommand.model_validate(orjson.loads(payload))
                            await self._handle_command(command)
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            logger.exception(
                                "Failed to handle orchestrator command",
                                message_id=message_id,
                            )
                            continue

                        await self._redis.xack(
                            config.ORCHESTRATOR.ORCH_COMMANDS_STREAM,
                            config.ORCHESTRATOR.ORCH_COMMANDS_GROUP,
                            message_id,
                        )

            except asyncio.CancelledError:
                raise
            except ResponseError as exc:
                if "NOGROUP" in str(exc):
                    logger.warning(
                        "Orchestrator commands consumer group is missing; recreating it",
                        stream=config.ORCHESTRATOR.ORCH_COMMANDS_STREAM,
                        group=config.ORCHESTRATOR.ORCH_COMMANDS_GROUP,
                    )
                    self._group_ready = False
                    await self._ensure_ready()
                    continue
                logger.exception("Failed to read orchestrator commands stream")
                await self._disconnect()
                await self._wait_before_retry()
            except (RedisConnectionError, RedisTimeoutError, OSError):
                logger.warning(
                    "Lost valkey connection for orchestrator commands stream; reconnecting",
                    stream=config.ORCHESTRATOR.ORCH_COMMANDS_STREAM,
                    group=config.ORCHESTRATOR.ORCH_COMMANDS_GROUP,
                )
                await self._disconnect()
                await self._wait_before_retry()
            except Exception:
                logger.exception("Failed to read orchestrator commands stream")
                await self._disconnect()
                await self._wait_before_retry()
