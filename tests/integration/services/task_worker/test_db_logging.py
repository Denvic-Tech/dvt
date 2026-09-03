from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from loguru import logger as loguru_logger
from sqlalchemy import Column, MetaData, String, Table, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.logger.db_sink import BatchedDBSink
from src.logger.formatters import sink_formatter
from src.models.db_log import LogRecord


pytestmark = [pytest.mark.asyncio, pytest.mark.docker_required]

async def test_worker_logs_are_persisted_with_exception_traceback(postgres_container):
    base_url = make_url(postgres_container.get_connection_url())
    schema_name = f"log_sink_{uuid4().hex[:8]}"

    admin_engine = create_engine(
        postgres_container.get_connection_url(),
        isolation_level="AUTOCOMMIT",
    )
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))

    existing_options = str(base_url.query.get("options", "")).strip()
    search_path_option = f"-csearch_path={schema_name}"
    merged_options = f"{existing_options} {search_path_option}".strip() if existing_options else search_path_option
    engine_url = base_url.set(
        query={
            **base_url.query,
            "options": merged_options,
        }
    )

    engine = create_async_engine(engine_url.render_as_string(hide_password=False))
    try:
        metadata = MetaData()
        Table("users", metadata, Column("id", String, primary_key=True))
        Table("tasks", metadata, Column("task_id", String, primary_key=True))
        LogRecord.__table__.to_metadata(metadata)

        async with engine.begin() as conn:
            await conn.run_sync(metadata.drop_all)
            await conn.run_sync(metadata.create_all)
            await conn.execute(text("INSERT INTO users (id) VALUES ('test-user')"))
            await conn.execute(
                text(
                    """
                    INSERT INTO tasks (task_id) VALUES
                    ('task-native'),
                    ('task-subprocess')
                    """
                )
            )

        sink = BatchedDBSink(
            engine=engine,
            service_name="task_worker_test",
            loop=asyncio.get_running_loop(),
            batch_size=1,
            flush_interval_sec=0.05,
            queue_maxsize=128,
        )
        handler_id = loguru_logger.add(
            sink,
            level="DEBUG",
            enqueue=False,
            catch=True,
            format=sink_formatter,
        )

        subprocess_traceback = (
            "Traceback (most recent call last):\n"
            "  File \"worker.py\", line 42, in run\n"
            "ValueError: invalid payload"
        )

        try:
            worker_log = loguru_logger.bind(user_id="test-user", task_id="task-native")
            worker_log.info("worker info")

            try:
                raise RuntimeError("pipeline exploded")
            except RuntimeError:
                worker_log.exception("worker exception")

            loguru_logger.bind(
                user_id="test-user",
                task_id="task-subprocess",
                traceback_str=subprocess_traceback,
            ).error("Task crashed in subprocess")

            await asyncio.sleep(0.2)
        finally:
            loguru_logger.remove(handler_id)
            await sink.close()

        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT task_id, level, message, exception_traceback
                        FROM logs
                        WHERE task_id IN ('task-native', 'task-subprocess')
                        ORDER BY task_id, created_at
                        """
                    )
                )
            ).mappings().all()

        native_rows = [row for row in rows if row["task_id"] == "task-native"]
        subprocess_rows = [row for row in rows if row["task_id"] == "task-subprocess"]

        assert len(native_rows) == 2
        assert len(subprocess_rows) == 1

        native_error_row = next(row for row in native_rows if row["level"] == "ERROR")
        assert native_error_row["message"] == "worker exception"
        assert "RuntimeError: pipeline exploded" in (native_error_row["exception_traceback"] or "")

        subprocess_error_row = subprocess_rows[0]
        assert subprocess_error_row["level"] == "ERROR"
        assert subprocess_error_row["message"] == "Task crashed in subprocess"
        assert subprocess_error_row["exception_traceback"] == subprocess_traceback
    finally:
        await engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        admin_engine.dispose()
