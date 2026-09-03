import sqlalchemy as sa
from clickhouse_sqlalchemy import types as clickhouse_types

import core.metadata.db_metadata.table as table_metadata_module
from core.metadata.db_metadata import load_db_table_metadata
from core.types import DataType, DBTableType


def test_load_db_table_metadata_returns_target_table_snapshot() -> None:
    engine = sa.create_engine('sqlite:///:memory:')
    metadata = sa.MetaData()
    table = sa.Table(
        'items',
        metadata,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
    )
    sa.Index('items_name_idx', table.c.name)
    metadata.create_all(engine)

    result = load_db_table_metadata(
        engine,
        table_name='items',
        database_name='catalog',
    )

    assert result.name == 'items'
    assert result.database_name == 'catalog'
    assert result.type == DBTableType.BASE_TABLE
    assert [column.name for column in result.columns] == ['id', 'name']
    assert result.columns[0].dtype == DataType.INT
    assert result.columns[0].primary_key is True
    assert result.columns[1].nullable is False
    assert result.columns[1].indexes == ['items_name_idx']


def test_load_db_table_metadata_rejects_missing_table() -> None:
    engine = sa.create_engine('sqlite:///:memory:')

    try:
        load_db_table_metadata(engine, table_name='missing')
    except ValueError as exc:
        assert 'missing' in str(exc)
    else:
        raise AssertionError('Expected missing table error.')


def test_load_db_table_metadata_maps_reflected_clickhouse_float_types(monkeypatch) -> None:
    class ClickHouseInspector:
        @staticmethod
        def has_table(table_name, schema=None):
            assert table_name == 'measurements'
            assert schema is None
            return True

        @staticmethod
        def get_pk_constraint(table_name, schema=None):
            assert table_name == 'measurements'
            assert schema is None
            return {}

        @staticmethod
        def get_indexes(table_name, schema=None):
            assert table_name == 'measurements'
            assert schema is None
            return []

        @staticmethod
        def get_columns(table_name, schema=None):
            assert table_name == 'measurements'
            assert schema is None
            return [
                {
                    'name': 'plain_float',
                    'type': clickhouse_types.Float64,
                    'nullable': False,
                },
                {
                    'name': 'nullable_float',
                    'type': clickhouse_types.Nullable(clickhouse_types.Float64),
                    'nullable': True,
                },
            ]

    monkeypatch.setattr(table_metadata_module.sa, 'inspect', lambda engine: ClickHouseInspector())

    result = load_db_table_metadata(object(), table_name='measurements')

    assert [column.dtype for column in result.columns] == [DataType.FLOAT, DataType.FLOAT]
    assert [column.nullable for column in result.columns] == [False, True]
