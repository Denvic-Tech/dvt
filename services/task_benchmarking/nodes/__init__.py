"""Benchmark-only nodes registered explicitly by the task_benchmarking runner.

Packages mirror the built-in node package contract (``node.yaml`` + ``NODE_CLASS``) but live
outside ``src/nodes``, so DVT discovery never registers them in Gateway or Task Workers.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from src.node_dsl._init_nodes import register_node_classes
from src.node_dsl.registry import nodes as nodes_registry
from src.node_dsl.registry._bootstrap import registry_transaction

if TYPE_CHECKING:
    from src.node_dsl import BaseNode

BENCHMARK_NODE_PACKAGES = (
    "benchmark_sql_connection",
    "benchmark_ensure_table",
    "benchmark_synthetic_dataframe",
    "benchmark_materialize",
)


def benchmark_node_classes() -> list[type[BaseNode]]:
    return [
        importlib.import_module(f"{__name__}.{package}").NODE_CLASS
        for package in BENCHMARK_NODE_PACKAGES
    ]


def register_benchmark_nodes() -> list[str]:
    """Register benchmark nodes once; returns the names registered by this call.

    The built-in bootstrap clears the registry before discovery, so it is forced first;
    registering earlier would be wiped by the bootstrap triggered on the first node lookup.
    """
    nodes_registry.get_all()
    with registry_transaction():
        missing = [
            node_cls
            for node_cls in benchmark_node_classes()
            if node_cls.__name__ not in nodes_registry.NODE_CLASSES
        ]
        register_node_classes(missing)
    return [node_cls.__name__ for node_cls in missing]
