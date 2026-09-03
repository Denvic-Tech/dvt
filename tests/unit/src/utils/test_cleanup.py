from datetime import UTC, datetime
from unittest.mock import MagicMock

from src.utils.cleanup import clean_old_logs


class ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class DeleteResult:
    def __init__(self, *, rowcount=None, scalar_value=None):
        self.rowcount = rowcount
        self._scalar_value = scalar_value

    def scalar(self):
        return self._scalar_value


def test_clean_old_logs_skips_error_logs_in_non_batch_delete():
    engine = MagicMock()
    connect_conn = MagicMock()
    begin_conn = MagicMock()

    engine.connect.return_value.__enter__.return_value = connect_conn
    engine.begin.return_value.__enter__.return_value = begin_conn
    connect_conn.execute.side_effect = [
        ScalarResult(True),
        ScalarResult(True),
        ScalarResult(True),
    ]
    begin_conn.execute.return_value = DeleteResult(rowcount=3)

    deleted = clean_old_logs(
        engine=engine,
        threshold=datetime(2026, 1, 1, tzinfo=UTC),
        batch_size=None,
    )

    assert deleted == 3
    delete_query = str(begin_conn.execute.call_args.args[0])
    assert "created_at < :ts" in delete_query
    assert "UPPER(level) != 'ERROR'" in delete_query


def test_clean_old_logs_skips_error_logs_in_batch_delete():
    engine = MagicMock()
    connect_conn = MagicMock()
    begin_conn = MagicMock()

    engine.connect.return_value.__enter__.return_value = connect_conn
    engine.begin.return_value.__enter__.return_value = begin_conn
    connect_conn.execute.side_effect = [
        ScalarResult(True),
        ScalarResult(True),
        ScalarResult(True),
    ]
    begin_conn.execute.side_effect = [
        DeleteResult(scalar_value=2),
        DeleteResult(scalar_value=0),
    ]

    deleted = clean_old_logs(
        engine=engine,
        threshold=datetime(2026, 1, 1, tzinfo=UTC),
        batch_size=2,
    )

    assert deleted == 2
    delete_query = str(begin_conn.execute.call_args_list[0].args[0])
    assert "created_at < :ts" in delete_query
    assert "UPPER(level) != 'ERROR'" in delete_query


def test_clean_old_logs_skips_cleanup_when_level_column_is_missing():
    engine = MagicMock()
    connect_conn = MagicMock()

    engine.connect.return_value.__enter__.return_value = connect_conn
    connect_conn.execute.side_effect = [
        ScalarResult(True),
        ScalarResult(True),
        ScalarResult(False),
    ]

    deleted = clean_old_logs(
        engine=engine,
        threshold=datetime(2026, 1, 1, tzinfo=UTC),
        batch_size=100,
    )

    assert deleted == 0
    engine.begin.assert_not_called()
