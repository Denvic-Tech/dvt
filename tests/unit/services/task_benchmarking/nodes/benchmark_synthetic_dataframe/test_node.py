import pytest

from services.task_benchmarking import metrics, synthetic
from services.task_benchmarking.nodes.benchmark_synthetic_dataframe import (
    BenchmarkSyntheticDataFrame,
)


@pytest.fixture
def generated_partitions(monkeypatch) -> list[int]:
    calls: list[int] = []
    generate_partition = synthetic.generate_partition

    def _spy(schema: str, spec: synthetic.PartitionSpec, seed: int):
        calls.append(spec.index)
        return generate_partition(schema, spec, seed)

    monkeypatch.setattr(synthetic, "generate_partition", _spy)
    return calls


def _make_node(**inputs) -> BenchmarkSyntheticDataFrame:
    return BenchmarkSyntheticDataFrame(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="data",
        **inputs,
    )


async def test_output_and_metadata_are_built_without_generating_data(generated_partitions) -> None:
    metrics.reset()
    node = _make_node(rows=1_000, npartitions=4, seed=7, schema="wide_mixed")

    node.process()
    metadata = await node.resolve_metadata()

    assert generated_partitions == []
    assert node.output.npartitions == 4
    assert node.output.known_divisions is False
    assert [column.name for column in metadata["output"].columns] == synthetic.column_names(
        "wide_mixed"
    )
    assert metrics.get_metrics() == {"data": {"rows": 1_000}}


def test_computing_one_partition_generates_only_that_partition(generated_partitions) -> None:
    node = _make_node(rows=1_000, npartitions=4, seed=7, schema="numeric")
    node.process()

    partition = node.output.partitions[2].compute(scheduler="sync")

    assert generated_partitions == [2]
    assert partition["id"].tolist() == list(range(500, 750))
    assert partition.dtypes.to_dict() == synthetic.partition_meta("numeric").dtypes.to_dict()
