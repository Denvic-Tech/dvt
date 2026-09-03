from __future__ import annotations

import json
from typing import Any, Optional

from src.pipeline import PipelineProcessor
from src.schemas.internal import TaskInternal

from .metadata import serialize_metadata
from .recorder import BenchmarkRecorder, NodeMemoryStats


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

    summary: dict[str, Any] = {
        "task_id": task.task_id,
        "project_id": task.project_id,
        "status": "success" if success else "error",
        "duration_s": duration_value,
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
                "duration_s": (
                    (recorder.node_stats[node_id].end_time - recorder.node_stats[node_id].start_time)
                    if node_id in recorder.node_stats and recorder.node_stats[node_id].end_time
                    else None
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
