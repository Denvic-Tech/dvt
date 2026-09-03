import orjson
from redis import asyncio as redis

from src.modules.task_execution.infra.transport import OrchestratorCommand

import config


async def publish_orchestrator_command(command: OrchestratorCommand) -> None:
    client = redis.from_url(config.CELERY.CELERY_BROKER_URL)
    try:
        await client.xadd(
            config.ORCHESTRATOR.ORCH_COMMANDS_STREAM,
            {"payload": orjson.dumps(command.model_dump(mode="json"))},
            maxlen=config.ORCHESTRATOR.ORCH_COMMANDS_MAXLEN,
            approximate=True,
        )
    finally:
        await client.aclose()
