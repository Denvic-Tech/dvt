from unittest.mock import patch

import dask.dataframe as dd
import numpy as np
import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine

from core.types import Column

from src.models import QueueTopicRecord
from src.nodes.extract.read_queue_topic import ReadQueueTopic
from src.pipeline.execution_mode import PipelineExecutionMode


class TestReadQueueTopic:
    """Группа тестов для ноды чтения из Redis Stream (Queue Topic)"""

    @pytest.fixture
    def mock_db_session(self):
        """Фикстура для временной базы метаданных в памяти"""
        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            # Создаем тестовый топик со схемой
            topic = QueueTopicRecord(
                id="test-topic-123",
                name="test_events",
                columns_schema=[
                    Column(name="user_id", dtype="INT", nullable=False),
                    Column(name="action", dtype="STRING", nullable=True),
                    Column(name="value", dtype="FLOAT", nullable=True),
                ]
            )
            session.add(topic)
            session.commit()
            session.refresh(topic)
            yield engine, topic

    @patch("src.nodes.extract.read_queue_topic.RedisTopicManager")
    @pytest.mark.asyncio
    async def test_read_queue_topic_success(self, MockRedisManager, mock_db_session):
        """Тестирует успешное чтение данных и преобразование в Dask DataFrame"""
        metadata_engine, topic = mock_db_session

        # Данные, которые якобы вернул Redis Stream
        mock_redis_data = [
            ("1712345678-0", {"user_id": "1", "action": "click", "value": "10.5"}),
            ("1712345679-0", {"user_id": "2", "action": "view", "value": "20.0"}),
        ]

        # Настраиваем мок менеджера Redis
        mock_manager = MockRedisManager.return_value

        # 1. Мокаем xlen, чтобы нода не посчитала поток пустым
        mock_manager.xlen.return_value = 2

        # 2. Мокаем получение границ потока (для параллельного чтения)
        mock_manager.get_stream_bounds.return_value = ("1712345678-0", "1712345679-0")

        # 3. Мокаем само чтение
        mock_manager.read_range_to_dataframe.return_value = pd.DataFrame([
            {"_stream_id": m[0], **m[1]} for m in mock_redis_data
        ])

        # Инициализируем ноду
        node = ReadQueueTopic(
            user_id="test_user",
            project_id="test_proj",
            task_id="test_task",
            node_id="node-redis-1",
            topic_id=topic.id
        )
        node.metadata_connection = metadata_engine

        # Выполняем ноду
        await node.execute(PipelineExecutionMode.FULL)

        # Проверки
        assert isinstance(node.output, dd.DataFrame)
        result_df = node.output.compute()

        assert len(result_df) == 2
        assert list(result_df["user_id"]) == [np.int64(1), np.int64(2)]
        assert result_df["value"].dtype == "float"

        # Проверяем вызовы
        mock_manager.xlen.assert_called()
        mock_manager.read_range_to_dataframe.assert_called()

    def test_infer_metadata(self, mock_db_session):
        """Тестирует инференс метаданных (схему) без выполнения ноды"""
        metadata_engine, topic = mock_db_session

        # Добавлены обязательные аргументы базового класса BaseNode
        node = ReadQueueTopic(
            user_id="test_u",
            project_id="test_p",
            task_id="test_t",
            node_id="test_n",
            topic_id=topic.id
        )
        node.metadata_connection = metadata_engine

        metadata = node.infer_metadata()
        columns = metadata["output"].columns

        col_names = [c.name for c in columns]
        assert "user_id" in col_names
        assert "action" in col_names

    @patch("src.nodes.extract.read_queue_topic.RedisTopicManager")
    @pytest.mark.asyncio
    async def test_read_with_custom_stream_key(self, MockRedisManager, mock_db_session):
        """Тестирует чтение с кастомным ключом стрима"""
        metadata_engine, topic = mock_db_session
        custom_key = "manual:stream:key"

        mock_manager = MockRedisManager.return_value
        mock_manager.xlen.return_value = 10
        mock_manager.read_range_to_dataframe.return_value = pd.DataFrame()
        # 2. Мокаем получение границ потока (для параллельного чтения)
        mock_manager.get_stream_bounds.return_value = ("1712345678-0", "1712345679-0")


        node = ReadQueueTopic(
            user_id="test_u",
            project_id="test_p",
            task_id="test_t",
            node_id="test_n",
            topic_id=topic.id,
            stream_key=custom_key
        )
        node.metadata_connection = metadata_engine
        await node.execute(PipelineExecutionMode.FULL)

        # Проверяем, что в менеджер ушел именно наш кастомный ключ
        args, kwargs = mock_manager.read_range_to_dataframe.call_args
        called_key = args[0] if args else kwargs.get('stream_key')
        assert called_key == custom_key
        # Также проверяем, что xlen вызывался с правильным ключом
        mock_manager.xlen.assert_called_with(custom_key)

    @pytest.mark.asyncio
    async def test_topic_not_found(self):
        """Тестирует поведение, если ID топика не существует в БД"""
        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        node = ReadQueueTopic(
            user_id="test_u",
            project_id="test_p",
            task_id="test_t",
            node_id="test_n",
            topic_id="non-existent"
        )
        node.metadata_connection = engine

        with pytest.raises(ValueError, match="Топик.*не найден"):
            await node.execute(PipelineExecutionMode.FULL)

    @patch("src.nodes.extract.read_queue_topic.RedisTopicManager")
    @pytest.mark.asyncio
    async def test_read_queue_topic_deletion_logic(self, MockRedisManager, mock_db_session):
        """Проверяет, что прочитанные ID отправляются на удаление в Redis при delete_after_read=True"""
        metadata_engine, topic = mock_db_session

        # Настраиваем моки
        mock_manager = MockRedisManager.return_value
        mock_redis_client = mock_manager._get_client.return_value

        stream_ids = ["1710000000-0", "1710000001-0"]
        mock_manager.xlen.return_value = 2
        mock_manager.get_stream_bounds.return_value = (stream_ids[0], stream_ids[1])

        # Имитируем возврат данных с колонкой _stream_id
        mock_manager.read_range_to_dataframe.return_value = pd.DataFrame([
            {"_stream_id": stream_ids[0], "user_id": 1},
            {"_stream_id": stream_ids[1], "user_id": 2},
        ])

        node = ReadQueueTopic(
            user_id="test_u",
            project_id="test_p",
            task_id="test_t",
            node_id="test_n",
            topic_id=topic.id,
            delete_after_read=True,  # Включаем удаление
            # Выставялем mode FULL, будто полностью выполняем pipeline
            execution_mode=PipelineExecutionMode.FULL
        )
        node.metadata_connection = metadata_engine

        await node.execute(PipelineExecutionMode.FULL)

        expected_key = f"queue_topic:{topic.id}:stream"
        mock_redis_client.xdel.assert_called_once_with(expected_key, *stream_ids)