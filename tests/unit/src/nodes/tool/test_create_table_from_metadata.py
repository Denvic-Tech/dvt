import sqlalchemy as sa
import pytest

from core.db.ddl import IndexSpec, TableCreateSpec
from core.types import Column, DataFrameMetadata, DataType
from src.nodes.tool.create_table import CreateTable


class _MetadataStoreStub:
    def __init__(self) -> None:
        self.removed_keys: list[str] = []

    async def remove(self, key: str) -> None:
        self.removed_keys.append(key)


def _build_metadata(*, include_name: bool = True, index_id: bool = True) -> DataFrameMetadata:
    columns = [
        Column(name="id", dtype=DataType.INT, nullable=False, index=index_id),
    ]
    if include_name:
        columns.append(
            Column(name="name", dtype=DataType.STRING, nullable=True, index=False),
        )
    return DataFrameMetadata(columns=columns)


def _build_node(
    *,
    connection: sa.Engine,
    dataframe_metadata: DataFrameMetadata,
    table_name: str = "events",
    on_exists: str = "error",
    table_create_spec: TableCreateSpec | None = None,
    metadata_store: _MetadataStoreStub | None = None,
) -> CreateTable:
    node = CreateTable(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-create-table-1",
        connection=connection,
        table_name=table_name,
        dataframe_metadata=dataframe_metadata,
        on_exists=on_exists,
        table_create_spec=table_create_spec,
        metadata_store=metadata_store,
    )
    return node


@pytest.mark.asyncio
async def test_create_table_from_metadata_creates_table_and_emits_signal(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'create_table.sqlite'}")

    node = _build_node(
        connection=engine,
        dataframe_metadata=_build_metadata(),
    )

    await node.process()

    inspector = sa.inspect(engine)
    assert inspector.has_table("events") is True
    assert [column["name"] for column in inspector.get_columns("events")] == ["id", "name"]
    assert node.signal_out is True


@pytest.mark.asyncio
async def test_create_table_from_metadata_on_exists_ignore_skips_recreate_and_cache_invalidation(
    tmp_path,
) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'create_table_ignore.sqlite'}")
    metadata_store = _MetadataStoreStub()

    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE events (id INTEGER PRIMARY KEY)")

    node = _build_node(
        connection=engine,
        dataframe_metadata=_build_metadata(include_name=True),
        on_exists="ignore",
        metadata_store=metadata_store,
    )
    node._meta_cache = True

    await node.process()

    inspector = sa.inspect(engine)
    assert [column["name"] for column in inspector.get_columns("events")] == ["id"]
    assert metadata_store.removed_keys == []
    assert node.signal_out is True


@pytest.mark.asyncio
async def test_create_table_from_metadata_on_exists_recreate_replaces_table(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'create_table_recreate.sqlite'}")

    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE events (id INTEGER PRIMARY KEY)")

    node = _build_node(
        connection=engine,
        dataframe_metadata=_build_metadata(include_name=True),
        on_exists="recreate",
    )

    await node.process()

    inspector = sa.inspect(engine)
    assert [column["name"] for column in inspector.get_columns("events")] == ["id", "name"]
    assert node.signal_out is True


@pytest.mark.asyncio
async def test_create_table_from_metadata_applies_table_create_spec(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'create_table_spec.sqlite'}")
    spec = TableCreateSpec(
        primary_key_cols="id",
        indexes=[IndexSpec(name="events_name_idx", columns=["name"], unique=True)],
    )

    node = _build_node(
        connection=engine,
        dataframe_metadata=_build_metadata(index_id=False),
        table_create_spec=spec,
    )

    await node.process()

    inspector = sa.inspect(engine)
    assert inspector.get_pk_constraint("events")["constrained_columns"] == ["id"]
    assert {index["name"] for index in inspector.get_indexes("events")} == {"events_name_idx"}


@pytest.mark.asyncio
async def test_create_table_from_metadata_invalidates_meta_cache_after_create(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'create_table_cache.sqlite'}")
    metadata_store = _MetadataStoreStub()
    node = _build_node(
        connection=engine,
        dataframe_metadata=_build_metadata(),
        metadata_store=metadata_store,
    )
    node._meta_cache = True

    await node.process()

    assert len(metadata_store.removed_keys) == 1
