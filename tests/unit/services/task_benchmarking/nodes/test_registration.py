import pytest

from services.task_benchmarking.nodes import benchmark_node_classes, register_benchmark_nodes

from src.exceptions import NodeNotFoundError
from src.node_dsl import registry


def test_register_benchmark_nodes_is_idempotent(benchmark_registry) -> None:
    names = [node_cls.__name__ for node_cls in benchmark_node_classes()]

    assert benchmark_registry == names
    assert register_benchmark_nodes() == []
    for name in names:
        assert registry.get_node(name).__name__ == name
        assert registry.get_definition(name).visible is False


def test_registered_nodes_survive_lookup_of_unknown_node(benchmark_registry) -> None:
    # A lookup miss may trigger the built-in bootstrap, which clears the registry first.
    with pytest.raises(NodeNotFoundError):
        registry.get_node("MissingBenchmarkNode")

    assert registry.get_node("BenchmarkMaterialize").__name__ == "BenchmarkMaterialize"
