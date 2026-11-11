from __future__ import annotations

import json
from typing import Any, Optional

from src.node_dsl.constants import NodeOutputNames
from src.node_dsl.registry import nodes as nodes_registry
from src.pipeline import PipelineProcessor
from src.schemas.internal import TaskInternal

from .metadata import serialize_metadata
from .metrics import get_metrics
from .recorder import BenchmarkRecorder, NodeMemoryStats

ROWS_WRITTEN_VARIABLE = "rows_written"


def node_order(task: TaskInternal, processor: PipelineProcessor) -> list[str]:
    result: list[str] = []
    result.extend(processor.executed_nodes)
    for node_id in processor.failed_nodes:
        if node_id not in result:
            result.append(node_id)
    for node_id in processor.skipped_nodes:
        if node_id not in result:
            result.append(node_id)
    for node_id in task.pipeline.keys():
        if node_id not in result:
            result.append(node_id)
    return result


def resolve_node_name(task: TaskInternal, stats: Optional[NodeMemoryStats], node_id: str) -> str:
    if stats is not None:
        return stats.node_name
    return task.pipeline[node_id].name


def _node_class(task: TaskInternal, node_id: str) -> Any:
    return nodes_registry.NODE_CLASSES.get(task.pipeline[node_id].name)


def _rows_written(node_cls: Any, outputs: dict[str, Any] | None) -> int | None:
    """``rows_written`` system variable emitted by a writer node (WriteDataFrameToDBV4)."""
    variables_model = getattr(node_cls, "SYSTEM_VARIABLES_MODEL", None)
    if variables_model is None or ROWS_WRITTEN_VARIABLE not in variables_model.model_fields:
        return None
    variables_output = (outputs or {}).get(NodeOutputNames.VARIABLES)
    variables = getattr(variables_output, "value", None) or {}
    value = getattr(variables.get(ROWS_WRITTEN_VARIABLE), "value", None)
    return None if value is None else int(value)


def collect_node_metrics(
    task: TaskInternal,
    processor: PipelineProcessor,
) -> dict[str, dict[str, Any]]:
    node_metrics = get_metrics()
    for node_id in task.pipeline:
        rows_written = _rows_written(
            _node_class(task, node_id),
            processor.nodes_outputs.get(node_id),
        )
        if rows_written is not None:
            node_metrics.setdefault(node_id, {}).setdefault("rows", rows_written)
    return node_metrics


def rows_per_second(rows: Any, duration_value: float | None) -> float | None:
    if not isinstance(rows, int) or isinstance(rows, bool):
        return None
    if duration_value is None or duration_value <= 0:
        return None
    return rows / duration_value


def sink_rows_total(task: TaskInternal, node_metrics: dict[str, dict[str, Any]]) -> int | None:
    rows = [
        node_metrics[node_id]["rows"]
        for node_id in task.pipeline
        if getattr(_node_class(task, node_id), "OUTPUT_NODE", False)
        and isinstance(node_metrics.get(node_id, {}).get("rows"), int)
    ]
    return sum(rows) if rows else None


def node_duration(recorder: BenchmarkRecorder, node_id: str) -> float | None:
    stats = recorder.node_stats.get(node_id)
    if stats is None or not stats.end_time:
        return None
    return stats.end_time - stats.start_time


def build_report_payload(
    *,
    task: TaskInternal,
    processor: PipelineProcessor,
    recorder: BenchmarkRecorder,
    success: bool,
    include_metadata: bool,
    ordered_nodes: Optional[list[str]] = None,
) -> dict[str, Any]:
    if ordered_nodes is None:
        ordered_nodes = node_order(task=task, processor=processor)

    task_stats = recorder.task_stats
    duration_value = None
    if task_stats.start_time is not None and task_stats.end_time is not None:
        duration_value = task_stats.end_time - task_stats.start_time

    overall_delta = None
    if task_stats.start_rss is not None and task_stats.end_rss is not None:
        overall_delta = task_stats.end_rss - task_stats.start_rss

    node_metrics = collect_node_metrics(task, processor)

    summary: dict[str, Any] = {
        "task_id": task.task_id,
        "project_id": task.project_id,
        "status": "success" if success else "error",
        "duration_s": duration_value,
        "rows_total": sink_rows_total(task, node_metrics),
        "cpu_user_s": task_stats.cpu_user_s,
        "cpu_system_s": task_stats.cpu_system_s,
        "cgroup_memory_peak_bytes": task_stats.cgroup_memory_peak_bytes,
        "overall": {
            "rss_start_bytes": task_stats.start_rss,
            "rss_end_bytes": task_stats.end_rss,
            "rss_peak_bytes": task_stats.peak_rss,
            "rss_delta_bytes": overall_delta,
        },
        "nodes": [
            {
                "node_id": node_id,
                "node_name": resolve_node_name(task, recorder.node_stats.get(node_id), node_id),
                "status": (
                    recorder.node_stats[node_id].status
                    if node_id in recorder.node_stats
                    else ("skipped" if node_id in processor.skipped_nodes else "not_executed")
                ),
                "duration_s": node_duration(recorder, node_id),
                "rows_per_s": rows_per_second(
                    node_metrics.get(node_id, {}).get("rows"),
                    node_duration(recorder, node_id),
                ),
                "rss_start_bytes": recorder.node_stats[node_id].start_rss
                if node_id in recorder.node_stats
                else None,
                "rss_end_bytes": recorder.node_stats[node_id].end_rss
                if node_id in recorder.node_stats
                else None,
                "rss_peak_bytes": recorder.node_stats[node_id].peak_rss
                if node_id in recorder.node_stats
                else None,
                "rss_delta_bytes": (
                    recorder.node_stats[node_id].end_rss - recorder.node_stats[node_id].start_rss
                    if node_id in recorder.node_stats and recorder.node_stats[node_id].end_rss is not None
                    else None
                ),
                "error": recorder.node_stats[node_id].error if node_id in recorder.node_stats else None,
                "metrics": node_metrics.get(node_id, {}),
            }
            for node_id in ordered_nodes
        ],
        "metadata_metrics": recorder.node_metadata_metrics,
    }

    if include_metadata:
        summary["metadata"] = {
            node_id: {
                output_name: serialize_metadata(meta)
                for output_name, meta in (recorder.node_metadata.get(node_id) or {}).items()
            }
            for node_id in ordered_nodes
        }
    return summary


def build_report_json(
    *,
    task: TaskInternal,
    processor: PipelineProcessor,
    recorder: BenchmarkRecorder,
    success: bool,
    include_metadata: bool,
) -> str:
    ordered_nodes = node_order(task=task, processor=processor)
    payload = build_report_payload(
        task=task,
        processor=processor,
        recorder=recorder,
        success=success,
        ordered_nodes=ordered_nodes,
        include_metadata=include_metadata,
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)
