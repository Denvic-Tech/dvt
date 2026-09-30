from types import SimpleNamespace

import pytest
from tests.unit.src.modules.kafka_consumption.test_commit import make_case
from tests.unit.src.nodes.extract.read_kafka_messages.test_node import node as read_node

from src.modules.kafka_consumption.domain.exceptions import KafkaInputError
from src.modules.kafka_consumption.infra.exceptions import KafkaCommitError
from src.node_dsl.variables import UnresolvedValue
from src.nodes.tool.commit_kafka_offsets import CommitKafkaOffsets
from src.pipeline.execution_mode import PipelineExecutionMode


def node(offsets=None):
    _, gateway, _ = make_case()
    n = CommitKafkaOffsets(
        user_id="u", project_id="p", task_id="t", node_id="commit",
        connection=SimpleNamespace(id="connection"),
        offsets=offsets if offsets is not None else {
            "schema_version": 1, "topic": "topic", "group_id": "group",
            "partitions": [{"partition": 0, "next_offset": 5}],
        },
    )
    n._gateway = lambda: gateway
    return n, gateway


@pytest.mark.asyncio
async def test_metadata_never_commits_or_publishes_success():
    n, gateway = node()
    await n.execute(PipelineExecutionMode.METADATA_ONLY)
    gateway.commit.assert_not_called()
    assert n.signal_out is False
    assert all(isinstance(v.value, UnresolvedValue) for v in n.output_variables.values())


def test_early_offsets_never_compute_source():
    reader, source = read_node()
    reader.process()
    n, gateway = node(reader.output_variables["kafka_offsets"].value)
    with pytest.raises(KafkaInputError, match="unresolved"):
        n.process()
    assert not source.calls
    gateway.commit.assert_not_called()
    assert not n.signal_out


@pytest.mark.parametrize("offsets", ["bad secret", {"password": "secret"}, None])
def test_invalid_input_never_builds_gateway(offsets):
    n, _ = node()
    n.offsets = offsets
    n._gateway = lambda: pytest.fail("must validate first")
    with pytest.raises(KafkaInputError) as error:
        n.process()
    assert "secret" not in str(error.value)


def test_success_then_error_cannot_leave_success_outputs():
    n, gateway = node()
    n.process()
    assert n.signal_out is True
    assert n.output_variables["kafka_partitions_committed"].value == 1
    gateway.commit.side_effect = KafkaCommitError("uncertain")
    with pytest.raises(KafkaCommitError):
        n.process()
    assert n.signal_out is False
    assert all(isinstance(v.value, UnresolvedValue) for v in n.output_variables.values())
