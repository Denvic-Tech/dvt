from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis

from services.gateway.deps.redis import get_redis
from services.gateway.utils.queue_topic_data import validate_data_against_schema

from src.crud import queue_topic as queue_topic_crud
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.schemas.http.common import CommonResponse
from src.schemas.http.queue_topic import (
    QueueTopicCreateSchema,
    QueueTopicDataSchema,
    QueueTopicDataSuccessSchema,
    QueueTopicReadSchema,
    QueueTopicUpdateSchema,
)

r = router = APIRouter()

@router.post("/{topic_id}/data", response_model=QueueTopicDataSuccessSchema)
async def submit_queue_topic_data(
    topic_id: str,
    request: QueueTopicDataSchema,
    session: AsyncSessionDepends,
    user: UserAccessOnly,  # noqa: ARG001
    redis: Annotated[Redis, Depends(get_redis)],
) -> QueueTopicDataSuccessSchema:
    topic = (await queue_topic_crud.get_queue_topics_by(session, topic_id=topic_id)).first()
    if not topic:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Топик очереди не найден"
        )

    # 2. Валидация данных
    try:
        validated_data = validate_data_against_schema(request.data, topic)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        ) from e

    # 3. Сохраняем данные в Redis Stream
    stream_key = f"queue_topic:{topic_id}:stream"
    added_count = 0

    # Используем пайплайн для пакетной вставки (XADD в пайплайне работает)
    async with redis.pipeline() as pipe:
        for record in validated_data:
            await pipe.xadd(stream_key, record, id="*")
        # Выполняем все команды
        results = await pipe.execute()
        added_count = len(results)

    return QueueTopicDataSuccessSchema(
        success=True,
        message="Данные успешно сохранены в Redis Stream",
        stored_count=added_count
    )

@router.get("", response_model=list[QueueTopicReadSchema])
async def get_queue_topics(
        session: AsyncSessionDepends,
        user: UserAccessOnly,  # noqa: ARG001
        name: str | None = None,
) -> list[QueueTopicReadSchema]:
    topics = (
        list(await queue_topic_crud.get_queue_topics_by(session, name=name))
        if name
        else list(await queue_topic_crud.get_queue_topics(session))
    )
    return [QueueTopicReadSchema.model_validate(topic) for topic in topics]


@router.post("", response_model=QueueTopicReadSchema)
async def create_queue_topic(
        data: QueueTopicCreateSchema,
        session: AsyncSessionDepends,
        user: UserAccessOnly,  # noqa: ARG001
) -> QueueTopicReadSchema:
    topic = await queue_topic_crud.create_queue_topic(
        session,
        name=data.name,
        columns_schema=data.columns_schema,
    )
    await session.commit()
    await session.refresh(topic)
    return QueueTopicReadSchema.model_validate(topic)


@router.get("/{topic_id}", response_model=QueueTopicReadSchema)
async def get_queue_topic(
        topic_id: str,
        session: AsyncSessionDepends,
        user: UserAccessOnly,  # noqa: ARG001
) -> QueueTopicReadSchema:
    topic = (await queue_topic_crud.get_queue_topics_by(session, topic_id=topic_id)).first()
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue topic not found")
    return QueueTopicReadSchema.model_validate(topic)


@router.patch("/{topic_id}", response_model=QueueTopicReadSchema)
async def update_queue_topic(
        topic_id: str,
        data: QueueTopicUpdateSchema,
        session: AsyncSessionDepends,
        user: UserAccessOnly,  # noqa: ARG001
) -> QueueTopicReadSchema:
    topic = await queue_topic_crud.update_queue_topic(
        session,
        topic_id=topic_id,
        name=data.name,
        columns_schema=data.columns_schema,
    )
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue topic not found")
    await session.commit()
    await session.refresh(topic)
    return QueueTopicReadSchema.model_validate(topic)


@router.delete("/{topic_id}", response_model=CommonResponse)
async def delete_queue_topic(
        topic_id: str,
        session: AsyncSessionDepends,
        user: UserAccessOnly,  # noqa: ARG001
) -> CommonResponse:
    deleted_ids = await queue_topic_crud.delete_queue_topics_by(session, topic_id=topic_id)
    if not deleted_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue topic not found")
    await session.commit()
    return CommonResponse(success=True, message="Queue topic successfully deleted.")
