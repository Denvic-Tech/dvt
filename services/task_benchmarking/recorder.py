from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import psutil

from src.node_dsl.types import NodeMetadata
from src.schemas.internal import TaskInternal

from .metadata import metadata_metrics


@dataclass
class NodeMemoryStats:
    node_id: str
    node_name: str
    start_time: float
    start_rss: int
    end_time: Optional[float] = None
    end_rss: Optional[int] = None
    peak_rss: Optional[int] = None
    status: str = "running"
    error: Optional[str] = None


@dataclass
class TaskMemoryStats:
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    start_rss: Optional[int] = None
    end_rss: Optional[int] = None
    peak_rss: Optional[int] = None
    status: str = "running"
    error: Optional[str] = None


class MemorySampler:
    def __init__(self, process: "psutil.Process", interval_sec: float) -> None:
        self._process = process
        self._interval_sec = interval_sec
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._peak_rss = 0

    def start(self) -> None:
        self._stop_event.clear()
        self._thread.start()

    def stop(self) -> int:
        self._stop_event.set()
        self._thread.join(timeout=1.0)
        return self._peak_rss

    def _run(self) -> None:
        while not self._stop_event.is_set():
            rss = self._process.memory_info().rss
            if rss > self._peak_rss:
                self._peak_rss = rss
            self._stop_event.wait(self._interval_sec)


class BenchmarkRecorder:
    def __init__(self, sample_interval_sec: float, collect_metadata: bool) -> None:
        self._process = psutil.Process(os.getpid())
        self._sample_interval_sec = sample_interval_sec
        self._lock = threading.Lock()
        self._collect_metadata = collect_metadata
        self.task_stats = TaskMemoryStats()
        self.node_stats: dict[str, NodeMemoryStats] = {}
        self.node_metadata: dict[str, NodeMetadata] = {}
        self.node_metadata_metrics: dict[str, dict[str, int]] = {}
        self._task_sampler: Optional[MemorySampler] = None
        self._node_samplers: dict[str, MemorySampler] = {}

    def _current_rss(self) -> int:
        return int(self._process.memory_info().rss)

    def on_task_started(self, task: TaskInternal) -> None:
        self.task_stats.start_time = time.perf_counter()
        self.task_stats.start_rss = self._current_rss()
        self._task_sampler = MemorySampler(self._process, self._sample_interval_sec)
        self._task_sampler.start()

    def on_task_success(self, task: TaskInternal) -> None:
        self._finish_task(status="success", error=None)

    def on_task_error(self, task: TaskInternal, message: str) -> None:
        self._finish_task(status="error", error=message)

    def on_task_canceled(self, task: TaskInternal) -> None:
        self._finish_task(status="canceled", error=None)

    def _finish_task(self, status: str, error: Optional[str]) -> None:
        self.task_stats.end_time = time.perf_counter()
        self.task_stats.end_rss = self._current_rss()
        self.task_stats.status = status
        self.task_stats.error = error
        if self._task_sampler:
            peak = self._task_sampler.stop()
            start_rss = self.task_stats.start_rss or 0
            end_rss = self.task_stats.end_rss or 0
            self.task_stats.peak_rss = max(peak, start_rss, end_rss)

    def on_node_start(self, user_id: str, project_id: str, task_id: str, node: Any) -> None:
        with self._lock:
            stats = NodeMemoryStats(
                node_id=node.node_id,
                node_name=node.__class__.__name__,
                start_time=time.perf_counter(),
                start_rss=self._current_rss(),
            )
            sampler = MemorySampler(self._process, self._sample_interval_sec)
            sampler.start()
            self.node_stats[node.node_id] = stats
            self._node_samplers[node.node_id] = sampler

    def on_node_success(self, user_id: str, project_id: str, task_id: str, node: Any) -> None:
        self._finish_node(node=node, status="success", error=None)

    def on_node_error(
        self,
        user_id: str,
        project_id: str,
        task_id: str,
        node: Any,
        message: str,
    ) -> None:
        self._finish_node(node=node, status="error", error=message)

    def on_node_metadata(
        self,
        user_id: str,
        project_id: str,
        task_id: str,
        node: Any,
        metadata: NodeMetadata,
    ) -> None:
        with self._lock:
            self.node_metadata_metrics[node.node_id] = metadata_metrics(metadata)
            if self._collect_metadata:
                self.node_metadata[node.node_id] = metadata

    def _finish_node(self, node: Any, status: str, error: Optional[str]) -> None:
        with self._lock:
            stats = self.node_stats.get(node.node_id)
            if stats is None:
                stats = NodeMemoryStats(
                    node_id=node.node_id,
                    node_name=node.__class__.__name__,
                    start_time=time.perf_counter(),
                    start_rss=self._current_rss(),
                )
                self.node_stats[node.node_id] = stats

            sampler = self._node_samplers.pop(node.node_id, None)
            peak = sampler.stop() if sampler else self._current_rss()
            end_rss = self._current_rss()

            stats.end_time = time.perf_counter()
            stats.end_rss = end_rss
            stats.peak_rss = max(peak, stats.start_rss, end_rss)
            stats.status = status
            stats.error = error
