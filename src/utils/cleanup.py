from datetime import datetime
from contextlib import contextmanager
from typing import Optional, Iterator

from sqlalchemy.engine import Engine
from sqlalchemy import text

from src import exceptions as exc
from src.logger import logger


class PgAdvisoryLock:
    """
    Контекст-менеджер для pg_try_advisory_lock/pg_advisory_unlock.
    Используется как lock_ctx при регистрации джобы.
    """

    def __init__(self, engine: Engine, key: int):
        self.engine = engine
        self.key = key

    @contextmanager
    def __call__(self) -> Iterator[None]:
        with self.engine.begin() as conn:
            ok = conn.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": self.key}
            ).scalar()
            if not ok:
                raise exc.SkipBackgroundRun(f"pg_try_advisory_lock({self.key}) failed")
            try:
                yield
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": self.key})


def clean_old_logs(
        *,
        engine: Engine,
        threshold: datetime,
        batch_size: Optional[int] = 5000
) -> int:
    """
    Удаляет записи из таблицы logs, у которых created_at < threshold.
    Перед удалением проверяет, что таблица и столбец существуют.
    Возвращает количество удалённых строк.
    """
    with engine.connect() as conn:
        table_exists = conn.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'logs'
                )
            """)
        ).scalar()

        if not table_exists:
            logger.warning("[logs_cleanup] - Таблица logs не существует, пропускаем")
            return 0

        column_exists = conn.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'logs'
                      AND column_name = 'created_at'
                )
            """)
        ).scalar()

        if not column_exists:
            logger.warning("[logs_cleanup] В таблице logs нет колонки created_at, пропускаем")
            return 0

        level_column_exists = conn.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'logs'
                      AND column_name = 'level'
                )
            """)
        ).scalar()

        if not level_column_exists:
            logger.warning("[logs_cleanup] В таблице logs нет колонки level, пропускаем")
            return 0

    total_deleted = 0
    with engine.begin() as conn:
        if not batch_size:
            res = conn.execute(
                text("DELETE FROM logs WHERE created_at < :ts AND UPPER(level) != 'ERROR'"),
                {"ts": threshold},
            )
            return res.rowcount or 0

        while True:
            deleted = conn.execute(
                text("""
                    WITH del AS (
                        DELETE FROM logs
                        WHERE id IN (
                            SELECT id
                            FROM logs
                            WHERE created_at < :ts
                              AND UPPER(level) != 'ERROR'
                            ORDER BY created_at
                            LIMIT :lim
                        )
                        RETURNING 1
                    )
                    SELECT COUNT(*) FROM del
                """),
                {"ts": threshold, "lim": batch_size},
            ).scalar() or 0
            total_deleted += deleted
            if deleted < batch_size:
                break

    return total_deleted
