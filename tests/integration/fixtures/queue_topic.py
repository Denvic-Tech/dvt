from typing import Generator, Any

import pytest

from core.types import Column, DataType
from src.models import QueueTopicRecord


@pytest.fixture()
def queue_topic_columns() -> list[Column]:
    return [
        Column(name="id", dtype=DataType.INT, nullable=False, index=True),
        Column(name="payload", dtype=DataType.STRING, nullable=True),
    ]


@pytest.fixture()
def test_queue_topic(test_db_session, queue_topic_columns) -> Generator[QueueTopicRecord, Any, None]:
    topic = QueueTopicRecord(name="topic-main", columns_schema=queue_topic_columns)
    test_db_session.add(topic)
    test_db_session.commit()
    test_db_session.refresh(topic)
    yield topic


@pytest.fixture()
def other_queue_topic(test_db_session, queue_topic_columns) -> Generator[QueueTopicRecord, Any, None]:
    topic = QueueTopicRecord(name="topic-other", columns_schema=queue_topic_columns)
    test_db_session.add(topic)
    test_db_session.commit()
    test_db_session.refresh(topic)
    yield topic
