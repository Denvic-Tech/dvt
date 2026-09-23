from unittest.mock import Mock

import dask.dataframe as dd
import pandas as pd
import pytest
import sqlalchemy as sa

from core.metadata import get_df_metadata
from core.types import DataType, DBColumn, DBTable, DBTableType

from src.modules.pipeline_cache import (
    CodecObjectStore,
    DumpEngineCodec,
    InMemoryBlobStore,
    InMemoryIndexStore,
)
from src.modules.pipeline_cache.domain.fingerprints import create_node_runtime_fingerprint
from src.nodes.extract.read_table_from_db_v3 import ReadTableFromDBV3, node as node_module
from src.pipeline.execution_mode import PipelineExecutionMode


def _table():
    return DBTable(
        name="source",
        comment="  Источник\nO'Brien  ",
        type=DBTableType.BASE_TABLE,
        columns=[
            DBColumn(name="id", dtype=DataType.INT, index=True, comment="Ключ"),
            DBColumn(name="value", dtype=DataType.FLOAT, comment="Сумма"),
            DBColumn(name="VALUE", dtype=DataType.STRING, comment="Иное поле"),
        ],
    )


def _node(**kwargs):
    return ReadTableFromDBV3(
        user_id="u",
        project_id="p",
        task_id="t",
        node_id="n",
        connection=sa.create_engine("sqlite:///:memory:"),
        table_name="source",
        columns=["id", "value"],
        partition_col="id",
        **kwargs,
    )


@pytest.mark.parametrize("rows", [0, 4])
def test_runtime_comments_match_exact_names_and_preserve_actual_schema(monkeypatch, rows):
    pdf = pd.DataFrame({"id": range(rows), "value": [1.5] * rows}).set_index("id")
    pdf["value"] = pdf["value"].astype("float64")
    output = dd.from_pandas(pdf, npartitions=1)
    loader = Mock(return_value=_table())
    monkeypatch.setattr(node_module, "load_db_table_metadata", loader)
    monkeypatch.setattr(node_module, "resolve_planner", lambda **kw: Mock())
    monkeypatch.setattr(node_module, "resolve_executor", lambda engine: Mock())
    monkeypatch.setattr(node_module, "frame_from_executor", lambda *args: output)
    node = _node()
    node.process()
    metadata = node.infer_metadata()["output"]
    assert metadata.comment == _table().comment
    assert {c.name: c.comment for c in metadata.columns} == {"id": "Ключ", "value": "Сумма"}
    expected = get_df_metadata(output)
    for actual, original in zip(metadata.columns, expected.columns, strict=True):
        assert actual.model_copy(update={"comment": None}) == original
    assert node.infer_metadata()["output"] == metadata
    loader.assert_called_once()


@pytest.mark.asyncio
async def test_metadata_only_comments_survive_empty_output_and_resolve_cache(monkeypatch):
    loader = Mock(return_value=_table())
    monkeypatch.setattr(node_module, "load_db_table_metadata", loader)
    node = _node()
    await node.process_metadata()
    metadata = (await node.resolve_metadata())["output"]
    assert metadata.comment == _table().comment
    assert {c.name: c.comment for c in metadata.columns} == {"id": "Ключ", "value": "Сумма"}
    assert node.infer_metadata()["output"].comment == _table().comment
    assert node.output._meta.empty
    loader.assert_called_once()


@pytest.mark.asyncio
async def test_read_node_execution_cache_restores_comments_without_source_access(monkeypatch):
    output = dd.from_pandas(pd.DataFrame({"id": [1, 2], "value": [1.5, 2.5]}), npartitions=2)
    monkeypatch.setattr(node_module, "load_db_table_metadata", Mock(return_value=_table()))
    monkeypatch.setattr(node_module, "resolve_planner", lambda **kw: Mock())
    monkeypatch.setattr(node_module, "resolve_executor", lambda engine: Mock())
    monkeypatch.setattr(node_module, "frame_from_executor", lambda *args: output)
    codec = DumpEngineCodec()
    store = CodecObjectStore(InMemoryBlobStore(default_ttl=600), codec)
    index = InMemoryIndexStore(
        serializer=codec.dump, deserializer=codec.load, default_ttl=600, separator=":::"
    )
    node = _node(data_store=store, data_index_store=index, store_enabled=True)
    await node.execute(PipelineExecutionMode.FULL)
    expected = node.output.compute(scheduler="threads")
    metadata = await node.resolve_metadata()
    await node.cache_execution_snapshot(outputs=node.get_outputs(), metadata=metadata)
    monkeypatch.setattr(node_module, "load_db_table_metadata", Mock(side_effect=AssertionError))
    restored = await ReadTableFromDBV3.restore_execution_snapshot(
        project_id="p",
        node_id="n",
        node_name="ReadTableFromDBV3",
        expected_output_names=tuple(node.get_outputs()),
        data_store=store,
        data_index_store=index,
        node_runtime_fingerprint=create_node_runtime_fingerprint(ReadTableFromDBV3),
    )
    assert restored is not None
    assert restored.metadata == metadata
    assert restored.metadata["output"].comment == _table().comment
    assert restored.metadata["output"].columns[0].comment == "Ключ"
    pd.testing.assert_frame_equal(restored.outputs["output"].value.compute(), expected)
