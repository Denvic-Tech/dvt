import pytest
import sqlalchemy as sa


@pytest.mark.asyncio
async def test_apply_column_actions_returns_refreshed_table_metadata(
    gateway_client,
    router_prefix,
    tmp_path,
) -> None:
    database_path = tmp_path / 'column_actions_metadata.sqlite'
    connection_string = f'sqlite:///{database_path.as_posix()}'
    engine = sa.create_engine(connection_string)
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE items (id INTEGER, old_value TEXT)'))

    response = await gateway_client.post(
        f'{router_prefix}/utils/ddl/apply-table-column-actions',
        json={
            'connection_id': connection_string,
            'table_name': 'items',
            'actions': [
                {
                    'type': 'add_column',
                    'column_name': 'new_value',
                    'column': {
                        'name': 'new_value',
                        'dtype': 'STRING',
                        'nullable': True,
                        'index': False,
                    },
                },
                {
                    'type': 'drop_column',
                    'column_name': 'old_value',
                },
            ],
        },
    )

    assert response.status_code == 200
    table_metadata = response.json()['table_metadata']
    assert table_metadata['name'] == 'items'
    assert [column['name'] for column in table_metadata['columns']] == [
        'id',
        'new_value',
    ]


@pytest.mark.asyncio
async def test_apply_column_actions_dry_run_omits_table_metadata(
    gateway_client,
    router_prefix,
    tmp_path,
) -> None:
    database_path = tmp_path / 'column_actions_dry_run_metadata.sqlite'
    connection_string = f'sqlite:///{database_path.as_posix()}'
    engine = sa.create_engine(connection_string)
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE items (id INTEGER)'))

    response = await gateway_client.post(
        f'{router_prefix}/utils/ddl/apply-table-column-actions',
        json={
            'connection_id': connection_string,
            'table_name': 'items',
            'dry_run': True,
            'actions': [
                {
                    'type': 'add_column',
                    'column_name': 'new_value',
                    'column': {
                        'name': 'new_value',
                        'dtype': 'STRING',
                        'nullable': True,
                        'index': False,
                    },
                },
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()['table_metadata'] is None
    assert [
        column['name'] for column in sa.inspect(engine).get_columns('items')
    ] == ['id']
