from datetime import UTC, datetime

import pytest
from tests.fixtures.kafka_read import MemoryKafka

from src.modules.kafka_consumption.domain.exceptions import KafkaInputError, KafkaPositionError
from src.modules.kafka_consumption.domain.value_objects import ReadLimits
from src.modules.kafka_consumption.flow.use_cases import PlanKafkaRead, ReadKafkaChunk
from src.modules.kafka_consumption.infra.dask_reader import KafkaDaskReader, read_slot_count


def plan(gateway, **kwargs):
    return PlanKafkaRead(gateway, lambda: None).execute(
        topic="topic", group_id="group", limits=kwargs.pop("limits", ReadLimits()), **kwargs
    )


@pytest.mark.parametrize(
    ("mode", "extra", "expected"),
    [
        ("earliest", {}, [0, 0]),
        ("latest", {}, [5, 4]),
        ("committed", {}, [0, 0]),
        ("committed", {"missing_offset_policy": "latest"}, [5, 4]),
        ("explicit", {"start_offsets": {"0": 2, "1": 3}}, [2, 3]),
        ("timestamp", {"start_timestamp": datetime.fromtimestamp(1700000000.002, UTC)}, [2, 2]),
        ("timestamp", {"start_timestamp": datetime(2030, 1, 1, tzinfo=UTC)}, [5, 4]),
    ],
)
def test_start_modes(mode, extra, expected):
    gateway = MemoryKafka()
    result = plan(gateway, start_mode=mode, **extra)
    assert [r.start for r in result.ranges] == expected
    assert not gateway.calls


@pytest.mark.parametrize(
    "extra",
    [
        {"partitions": []},
        {"partitions": [0, 0]},
        {"partitions": [2]},
        {"partitions": [True]},
        {"start_mode": "other"},
        {"start_mode": "explicit", "start_offsets": {"0": 1}},
        {"start_mode": "explicit", "start_offsets": {"0": True, "1": 0}},
        {"start_mode": "timestamp", "start_timestamp": datetime(2026, 1, 1)},
    ],
)
def test_invalid_settings(extra):
    with pytest.raises(KafkaInputError):
        plan(MemoryKafka(), **extra)


def test_missing_and_unavailable_positions():
    gateway = MemoryKafka()
    with pytest.raises(KafkaPositionError):
        plan(gateway, missing_offset_policy="error")
    gateway.commits[0] = 7
    with pytest.raises(KafkaPositionError):
        plan(gateway)
    gateway.commits[0] = 2
    assert plan(gateway, partitions=[0]).ranges[0].start == 2


def reader(gateway, **limits):
    p = plan(gateway, limits=ReadLimits(**limits))
    use_case = ReadKafkaChunk(gateway, lambda: None)
    results = []
    result = KafkaDaskReader(
        p,
        read_chunk=use_case.execute,
        replay_chunk=use_case.replay,
        publish=results.append,
        invalidate=lambda: None,
        check_cancelled=lambda: None,
    )
    return result, results


@pytest.mark.parametrize(
    ("limits", "count", "size", "reason"),
    [
        ({"max_messages": 3, "rows_per_partition": 2}, 3, 9, "max_messages"),
        ({"max_bytes": 8}, 2, 6, "max_bytes"),
        ({"max_bytes": 9}, 3, 9, "max_bytes"),
        ({"max_bytes": None, "max_messages": None}, 9, 27, "snapshot_exhausted"),
    ],
)
def test_global_limits(limits, count, size, reason):
    r, results = reader(MemoryKafka(), **limits)
    df = r.dataframe().compute(scheduler="sync")
    assert len(df) == count
    assert results[0].messages_read == count
    assert results[0].bytes_read == size
    assert results[0].stop_reason == reason


def test_gaps_zero_payload_and_empty_tail():
    gateway = MemoryKafka({0: [(0, b""), (4, None)], 1: [(8, b"")]})
    r, results = reader(gateway, rows_per_partition=2, max_messages=None, max_bytes=None)
    df = r.dataframe().compute()
    assert len(df) == 3
    assert results[0].messages_read == 3 and results[0].bytes_read == 0
    assert [p.next_offset for p in results[0].partitions] == [5, 9]
    assert all(receipt.message_count <= 2 for receipt in r.receipts.values())


def test_planning_limit_does_not_claim_success():
    p = plan(MemoryKafka(), limits=ReadLimits(rows_per_partition=1))
    with pytest.raises(KafkaInputError, match="planning limit"):
        read_slot_count(p, 2)


def test_partitions_fill_a_chunk_instead_of_spending_extra_slots():
    gateway = MemoryKafka({p: [(0, b"")] for p in range(30)})
    r, results = reader(
        gateway,
        max_messages=None,
        max_bytes=None,
        rows_per_partition=10,
        max_message_bytes=1,
        target_partition_bytes=100,
    )
    assert len(r.dataframe().compute()) == 30
    assert [x.message_count for x in r.receipts.values() if x.message_count] == [10, 10, 10]
    assert results[0].messages_read == 30
