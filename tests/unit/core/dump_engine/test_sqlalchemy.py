import sqlalchemy as sa

from core.dump_engine._sqlalchemy import SAEngineCacheEngine


def test_can_handle_engine():
    engine = SAEngineCacheEngine()

    sa_engine = sa.create_engine("sqlite+pysqlite:///:memory:")

    assert engine.can_handle(sa_engine) is True
    assert engine.can_handle("sqlite+pysqlite:///:memory:") is False


def test_dump_load_roundtrip_sqlite_url():
    engine = SAEngineCacheEngine()

    original = sa.create_engine("sqlite+pysqlite:///dvt_dump_engine.db?check_same_thread=false")

    data, meta = engine.dump(original)
    restored = engine.load(data, meta=meta)

    assert meta is None
    assert isinstance(restored, sa.Engine)
    assert restored.url.drivername == original.url.drivername
    assert restored.url.database == original.url.database
    assert restored.url.query == original.url.query
