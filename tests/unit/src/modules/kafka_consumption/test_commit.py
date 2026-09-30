from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from src.modules.kafka_consumption.domain.entities import ReadSummary
from src.modules.kafka_consumption.domain.exceptions import KafkaInputError, KafkaPositionError
from src.modules.kafka_consumption.domain.value_objects import PartitionOffsets, TopicPartition
from src.modules.kafka_consumption.flow.use_cases import CommitKafkaOffsets
from src.modules.kafka_consumption.infra.exceptions import KafkaCommitError
from src.modules.kafka_consumption.infra.mappers import offsets_from_json
from src.node_dsl.exceptions import NodeExecutionCancelled


def make_case(current=None):
    gateway = MagicMock()
    tp = TopicPartition("topic", 0)
    gateway.partitions.return_value = (0, 1)
    gateway.cluster_id.return_value = "cluster"
    gateway.bounds.return_value = {tp: (0, 10), TopicPartition("topic", 1): (0, 10)}
    gateway.committed.return_value = {tp: current, TopicPartition("topic", 1): None}
    summary = ReadSummary("topic", "group", (PartitionOffsets(0, 5),), cluster_id="cluster")
    return CommitKafkaOffsets(gateway, lambda: None), gateway, summary


@pytest.mark.parametrize(
    "current,status,count", [(None, "committed", 1), (2, "committed", 1),
                             (5, "unchanged", 0), (7, "already_ahead", 0)]
)
def test_positions(current, status, count):
    case, gateway, summary = make_case(current)
    result = case.execute(summary)
    assert result.partitions[0].status == status
    assert result.partitions[0].current == current
    assert result.partitions[0].resulting == max(5, current or 0)
    assert result.partitions_committed == count
    if count:
        gateway.commit.assert_called_once_with("group", {TopicPartition("topic", 0): 5})
    else:
        gateway.commit.assert_not_called()
    gateway.read.assert_not_called()


def test_empty_and_diagnostic_connection():
    case, gateway, summary = make_case()
    result = case.execute(replace(summary, partitions=(), connection_id="another-connection"))
    assert result.partitions == () and result.partitions_committed == 0
    gateway.commit.assert_not_called()
    gateway.bounds.assert_not_called()
    assert case.execute(replace(summary, connection_id="other")).partitions_committed == 1


@pytest.mark.parametrize("cluster", ["other", None])
def test_cluster_mismatch_or_unavailable(cluster):
    case, gateway, summary = make_case()
    gateway.cluster_id.return_value = cluster
    with pytest.raises(KafkaInputError, match="cluster"):
        case.execute(summary)
    gateway.commit.assert_not_called()


def test_all_bounds_validated_before_commit_and_isolation_forwarded():
    case, gateway, summary = make_case()
    summary = replace(summary, partitions=(PartitionOffsets(0, 5), PartitionOffsets(1, 11)),
                      isolation_level="read_uncommitted")
    with pytest.raises(KafkaPositionError):
        case.execute(summary)
    gateway.commit.assert_not_called()
    assert gateway.bounds.call_args.args[1] == "read_uncommitted"


def test_unknown_partition():
    case, gateway, summary = make_case()
    with pytest.raises(KafkaInputError, match="partition"):
        case.execute(replace(summary, partitions=(PartitionOffsets(9, 0),)))
    gateway.commit.assert_not_called()


def test_failure_propagates_without_rollback():
    case, gateway, summary = make_case()
    gateway.commit.side_effect = KafkaCommitError("offsets may be saved")
    with pytest.raises(KafkaCommitError):
        case.execute(summary)
    assert gateway.commit.call_count == 1


def test_cancel_immediately_before_submission():
    case, gateway, summary = make_case()
    stopped = [False]
    def check():
        if stopped[0]:
            raise NodeExecutionCancelled("stop")
    case.check_cancelled = check
    original = gateway.committed.return_value
    def committed(*_):
        stopped[0] = True
        return original
    gateway.committed.side_effect = committed
    with pytest.raises(NodeExecutionCancelled):
        case.execute(summary)
    gateway.commit.assert_not_called()


@pytest.mark.parametrize("patch", [
    {"schema_version": 2}, {"schema_version": True}, {"topic": " "},
    {"group_id": ""}, {"cluster_id": ""}, {"isolation_level": "bad"},
    {"partitions": [{"partition": 0, "next_offset": True}]},
    {"partitions": [{"partition": 0, "next_offset": -1}]},
    {"partitions": [{"partition": 0, "next_offset": 1.5}]},
    {"partitions": [{"partition": 0, "next_offset": "1"}]},
    {"partitions": [{"partition": 0, "next_offset": 1}] * 2},
    {"partitions": [{"partition": False, "next_offset": 1}]},
    {"partitions": [{"partition": 0, "next_offset": 1, "last_message_offset": 1}]},
    {"secret": "payload-must-not-leak"},
])
def test_json_validation_is_safe(patch):
    payload = {"schema_version": 1, "topic": "topic", "group_id": "group", "partitions": []}
    with pytest.raises(KafkaInputError) as error:
        offsets_from_json({**payload, **patch})
    assert "payload-must-not-leak" not in str(error.value)
