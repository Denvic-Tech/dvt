from types import SimpleNamespace

import sqlalchemy as sa

from core.types import Column, DataFrameMetadata, DataType
from core.types.db_column import DBColumn

from src.modules.data_catalog.infra import build_observation, build_port_observations
from src.node_dsl.connection_types import SqlConnectionRecord
from src.pipeline.execution_mode import PipelineExecutionMode


class ReadTableFromDBV3:  # имя класса важно: наблюдатель фильтрует по нему
    def __init__(self, **attrs):
        self.__dict__.update(attrs)


class WriteDataFrameToDBV4(ReadTableFromDBV3):
    pass


def _connection(updated_at=None):
    record = SimpleNamespace(id="conn-1", kind="sql", type="postgres", updated_at=updated_at)
    connection = SqlConnectionRecord.__new__(SqlConnectionRecord)
    object.__setattr__(connection, "record", record)
    return connection


def _node(cls=ReadTableFromDBV3, **overrides):
    attrs = {
        "node_id": "node-1",
        "connection": _connection(),
        "execution_mode": PipelineExecutionMode.METADATA_ONLY,
        "table_name": "Orders",
        "schema_name": "public",
        "database_name": None,
        "columns": None,
    }
    attrs.update(overrides)
    return cls(**attrs)


def _metadata(*columns):
    return {"output": DataFrameMetadata(columns=list(columns))}


DB_COLUMNS = (
    DBColumn(name="id", dtype=DataType.INT, nullable=False, primary_key=True, comment="pk"),
    DBColumn(name="name", dtype=DataType.STRING, nullable=True),
)


def test_metadata_only_run_with_db_columns_is_trusted():
    observation = build_observation(_node(), _metadata(*DB_COLUMNS), project_id="p1")

    assert observation is not None
    assert (observation.project_id, observation.node_id, observation.connection_id) == ("p1", "node-1", "conn-1")
    assert observation.trust_types is True
    assert observation.partial is False
    assert observation.locator_parts == {"table": "Orders", "schema": "public", "database": None}
    assert [(f.name, f.dtype, f.ordinal, f.primary_key, f.comment) for f in observation.fields] == [
        ("id", "INT", 1, True, "pk"),
        ("name", "STRING", 2, False, None),
    ]
    assert observation.connection_revision == "unversioned"


def test_full_run_or_plain_columns_are_not_trusted_and_columns_subset_is_partial():
    full = build_observation(
        _node(execution_mode=PipelineExecutionMode.FULL, columns=["id"]), _metadata(*DB_COLUMNS), project_id="p1"
    )
    assert full.trust_types is False and full.partial is True

    restored = build_observation(
        _node(), _metadata(Column(name="id", dtype=DataType.INT)), project_id="p1"
    )
    assert restored.trust_types is False, "после кэша метаданных DBColumn вырождается в Column"


def test_port_observations_cover_every_dataframe_output_of_any_node():
    metadata = {
        "output": DataFrameMetadata(columns=list(DB_COLUMNS)),
        "inverted_output": DataFrameMetadata(columns=[Column(name="id", dtype=DataType.INT)]),
        "output_variables": "not a dataframe",
    }

    observed = build_port_observations(_node(WriteDataFrameToDBV4, node_id="exec-1"), metadata, project_id="p1", task_id="t1")

    assert [(item.node_id, item.port, item.names, item.task_id) for item in observed] == [
        ("exec-1", "output", ("id", "name"), "t1"),
        ("exec-1", "inverted_output", ("id",), "t1"),
    ]
    first = observed[0].columns
    assert [(c.name, c.dtype, c.nullable, c.ordinal) for c in first] == [("id", "INT", False, 1), ("name", "STRING", True, 2)]
    assert observed[0].graph_revision is None, "the use case fills the revision from the project stamp"

    assert build_port_observations(_node(node_id="__service_output__x"), metadata, project_id="p1") == ()
    assert build_port_observations(_node(), {"output": "not metadata"}, project_id="p1") == ()
    assert build_port_observations(_node(), None, project_id="p1") == ()


def test_skip_rules():
    assert build_observation(_node(WriteDataFrameToDBV4), _metadata(*DB_COLUMNS), project_id="p1") is None
    assert build_observation(_node(node_id="__service_output__"), _metadata(*DB_COLUMNS), project_id="p1") is None
    assert build_observation(_node(connection=sa.create_mock_engine("postgresql://", lambda *a, **k: None)), _metadata(*DB_COLUMNS), project_id="p1") is None
    assert build_observation(_node(), _metadata(), project_id="p1") is None
    assert build_observation(_node(), {"output": "not metadata"}, project_id="p1") is None
    assert build_observation(_node(), None, project_id="p1") is None
