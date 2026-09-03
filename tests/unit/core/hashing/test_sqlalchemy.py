import sqlalchemy as sa

from core.hashing._sqlalchemy import _get_sa_engine_hash


def test_sa_engine_hash_stable_for_same_url():
    engine = sa.create_engine("sqlite+pysqlite:///hashing_test.db")

    assert _get_sa_engine_hash(engine) == _get_sa_engine_hash(engine)


def test_sa_engine_hash_changes_with_execution_options():
    engine = sa.create_engine("sqlite+pysqlite:///hashing_test.db")
    engine_with_opts = engine.execution_options(stream_results=True)

    assert _get_sa_engine_hash(engine) != _get_sa_engine_hash(engine_with_opts)


def test_sa_engine_hash_changes_with_url():
    engine_a = sa.create_engine("sqlite+pysqlite:///hashing_test_a.db")
    engine_b = sa.create_engine("sqlite+pysqlite:///hashing_test_b.db")

    assert _get_sa_engine_hash(engine_a) != _get_sa_engine_hash(engine_b)
