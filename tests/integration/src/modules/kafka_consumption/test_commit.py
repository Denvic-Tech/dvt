import asyncio
import json
import os
import subprocess
import sys
import threading
from uuid import uuid4

import pytest
import sqlalchemy as sa
from tests.fixtures.kafka_commit import graph, kafka_connection, processor
from tests.integration.src.modules.kafka_consumption.test_lazy_read import make_node

from src.modules.kafka_consumption.facade import CommitKafkaOffsets, build_kafka_gateway
from src.modules.kafka_consumption.infra.exceptions import KafkaCommitError
from src.modules.kafka_consumption.infra.gateways.kafka_python import KafkaRuntimeSettings
from src.modules.kafka_consumption.infra.mappers import offsets_from_json
from src.modules.pipeline_cache import (
    CodecObjectStore,
    DumpEngineCodec,
    InMemoryBlobStore,
    InMemoryIndexStore,
)
from src.node_dsl.variables import UnresolvedValue

pytestmark = pytest.mark.docker_required


@pytest.fixture
def destination(postgres_container):
    engine = sa.create_engine(postgres_container.get_connection_url())
    tables = ["kafka_" + uuid4().hex for _ in range(2)]
    try:
        with engine.begin() as conn:
            for table in tables:
                conn.exec_driver_sql(f'CREATE TABLE {table} (value TEXT CHECK (value <> \'reject\'))')
        yield engine, tables
    finally:
        with engine.begin() as conn:
            for table in tables:
                conn.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")
        engine.dispose()


def values(engine, table):
    with engine.connect() as conn:
        return sorted(conn.scalars(sa.text(f"SELECT value FROM {table}")).all())


def gateway(broker, **kwargs):
    return build_kafka_gateway(
        properties=broker.dvt_properties, secrets=broker.dvt_secrets,
        check_cancelled=kwargs.pop("check_cancelled", lambda: None), **kwargs,
    )


def test_pipeline_writes_all_destinations_then_commits_and_reads_remainder(
    kafka_container, kafka_resources, destination,
):
    r = kafka_resources
    topic, group = r.topic(partitions=2), r.group()
    r.publish(topic, [
        {"partition": 0, "value": b"keep0"}, {"partition": 0, "value": b"drop"},
        {"partition": 0, "value": b"keep1"}, {"partition": 1, "value": b"keep2"},
        {"partition": 1, "value": b"keep3"},
    ])
    engine, tables = destination
    pipeline = graph(kafka_connection(kafka_container.dvt_properties), engine, topic, group, tables)
    codec = DumpEngineCodec()
    store = CodecObjectStore(InMemoryBlobStore(default_ttl=600), codec)
    index = InMemoryIndexStore(serializer=codec.dump, deserializer=codec.load, default_ttl=600)
    read_ids = []
    for iteration, expected in enumerate([["keep0", "keep2"], ["keep0", "keep1", "keep2", "keep3"]]):
        observed = []
        before = {0: None, 1: None} if iteration == 0 else {0: 2, 1: 1}

        def on_start(before=before, expected=expected, observed=observed, **kwargs):
            node = kwargs["node"]
            if node.node_id.startswith("write"):
                assert r.committed(topic, group) == before
            if node.node_id == "commit":
                assert r.committed(topic, group) == before
                assert all(values(engine, table) == expected for table in tables)
                assert not isinstance(node.input_variables["kafka_offsets"].value, UnresolvedValue)
                observed.append(node.offsets)

        proc = processor(pipeline, project=topic, run=str(iteration), data_store=store,
                         data_index_store=index, on_node_process_start=on_start)
        result = asyncio.run(proc.process())
        assert result.success and not proc.failed_nodes, result
        assert proc.node_signal_states["commit"]["signal_out"] is True
        assert proc.restored_nodes == []
        assert len(observed) == 1
        read_ids.append(observed[0]["read_id"])
        assert observed[0]["messages_read"] == (3 if iteration == 0 else 2)
        assert r.committed(topic, group) == ({0: 2, 1: 1} if iteration == 0 else {0: 3, 1: 2})
        print("KAFKA_COMMIT_JSON", json.dumps(observed[0]))
        print("KAFKA_COMMIT_RESULT", json.dumps(
            proc.nodes_outputs["commit"]["output_variables"].value["kafka_commit_result"].value
        ))
    assert len(set(read_ids)) == 2


@pytest.mark.parametrize("failure", ["write", "stop_before_write", "stop_after_write"])
def test_pipeline_failure_preserves_offsets_and_allows_replay(
    kafka_container, kafka_resources, destination, failure,
):
    r = kafka_resources
    topic, group = r.topic(partitions=2), r.group()
    payload = b"reject" if failure == "write" else b"keep"
    r.publish(topic, [{"partition": 0, "value": payload}, {"partition": 1, "value": b"keep2"}])
    engine, tables = destination
    pipeline = graph(kafka_connection(kafka_container.dvt_properties), engine, topic, group, tables[:1])
    stop = threading.Event()
    started = []
    def on_start(**kw):
        node = kw["node"]
        started.append(node.node_id)
        if failure == "stop_before_write" and node.node_id == "write0":
            stop.set()
            node.cancellation.raise_if_requested()
    def on_success(**kw):
        if failure == "stop_after_write" and kw["node"].node_id == "write0":
            stop.set()
    proc = processor(pipeline, project=topic, stop_event=stop,
                     on_node_process_start=on_start, on_node_process_success=on_success)
    asyncio.run(proc.process())
    assert "commit" not in started
    assert r.committed(topic, group) == {0: None, 1: None}
    if failure == "stop_after_write":
        assert values(engine, tables[0]) == ["keep", "keep2"]
    if failure == "stop_before_write":
        assert values(engine, tables[0]) == []
    read = make_node(kafka_container, topic, group)
    read.process()
    assert len(read.output.compute()) == 2


def test_saved_json_in_new_process_and_repeated_stale_commit(kafka_container, kafka_resources):
    r = kafka_resources
    topic, group = r.topic(partitions=2), r.group()
    r.publish(topic, [{"partition": p, "value": b"event"} for p in (0, 0, 1)])
    # The reader process exits before the independent commit process is launched.
    script = """
import json, sys
from types import SimpleNamespace
from src.nodes.extract.read_kafka_messages import ReadKafkaMessages
from src.nodes.tool.commit_kafka_offsets import CommitKafkaOffsets
data = json.load(sys.stdin)
connection = SimpleNamespace(id='another-accessible-connection', properties=data['properties'], secrets={})
common = dict(user_id='u', project_id='p', task_id='t', node_id='n', connection=connection)
if data['operation'] == 'read':
    node = ReadKafkaMessages(**common, topic=data['topic'], group_id=data['group'])
    node.process()
    node.output.compute(scheduler='sync')
    output = node.output_variables['kafka_offsets'].value
else:
    node = CommitKafkaOffsets(**common, offsets=data['offsets'])
    node.process()
    output = node.output_variables['kafka_commit_result'].value
print('RESULT_JSON=' + json.dumps(output))
"""
    def run(operation, **extra):
        data = dict(operation=operation, properties=kafka_container.dvt_properties, **extra)
        output = subprocess.run([sys.executable, "-c", script], input=json.dumps(data),
                                capture_output=True, text=True, timeout=120, check=False,
                                env=os.environ.copy())
        assert output.returncode == 0, output.stderr
        return json.loads(next(line.removeprefix("RESULT_JSON=") for line in output.stdout.splitlines()
                               if line.startswith("RESULT_JSON=")))
    saved = run("read", topic=topic, group=group)
    assert r.committed(topic, group) == {0: None, 1: None}
    first = run("commit", offsets=saved)
    assert all(p["status"] == "committed" for p in first["partitions"])
    assert all(p["status"] == "unchanged" for p in run("commit", offsets=saved)["partitions"])
    stale = {"schema_version": 1, "topic": topic, "group_id": group,
             "partitions": [{"partition": 0, "next_offset": 1}]}
    assert run("commit", offsets=stale)["partitions"][0]["status"] == "already_ahead"
    assert r.committed(topic, group) == {0: 2, 1: 1}


@pytest.mark.parametrize("failure", ["partial", "lost_response"])
def test_real_saved_offsets_survive_adapter_failure_and_replay(
    kafka_container, kafka_resources, failure,
):
    r = kafka_resources
    topic, group = r.topic(partitions=2), r.group()
    r.publish(topic, [{"partition": p, "value": b"event"} for p in (0, 1)])
    payload = {"schema_version": 1, "topic": topic, "group_id": group,
               "partitions": [{"partition": p, "next_offset": 1} for p in (0, 1)]}
    g = gateway(kafka_container, settings=KafkaRuntimeSettings(attempts=1))
    original = g.commit

    # Inject only the response failure; the writes go to the real broker.
    def fail(group_id, positions):
        selected = dict(list(positions.items())[:1]) if failure == "partial" else positions
        original(group_id, selected)
        raise KafkaCommitError("Response unavailable; offsets may already be saved")
    g.commit = fail
    with pytest.raises(KafkaCommitError):
        CommitKafkaOffsets(g, lambda: None).execute(offsets_from_json(payload))
    assert r.committed(topic, group) == ({0: 1, 1: None} if failure == "partial" else {0: 1, 1: 1})
    result = CommitKafkaOffsets(gateway(kafka_container), lambda: None).execute(offsets_from_json(payload))
    assert [p.status for p in result.partitions] == (
        ["unchanged", "committed"] if failure == "partial" else ["unchanged", "unchanged"]
    )
    assert r.committed(topic, group) == {0: 1, 1: 1}
