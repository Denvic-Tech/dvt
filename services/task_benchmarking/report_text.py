from __future__ import annotations

import json

from src.pipeline import PipelineProcessor
from src.schemas.internal import TaskInternal

from .metadata import dumps_metadata, serialize_metadata
from .recorder import BenchmarkRecorder
from .report_json import build_report_payload, node_order, resolve_node_name
from .utils import bytes_to_mib, duration_s, format_table


def _build_node_rows(
    *,
    task: TaskInternal,
    processor: PipelineProcessor,
    recorder: BenchmarkRecorder,
    ordered_nodes: list[str],
) -> list[list[str]]:
    rows: list[list[str]] = []
    for node_id in ordered_nodes:
        pipeline_node = task.pipeline[node_id]
        stats = recorder.node_stats.get(node_id)
        if stats:
            end_time = stats.end_time or stats.start_time
            rss_delta = None
            if stats.end_rss is not None:
                rss_delta = stats.end_rss - stats.start_rss
            rows.append(
                [
                    node_id,
                    stats.node_name,
                    stats.status,
                    duration_s(stats.start_time, end_time),
                    bytes_to_mib(stats.start_rss),
                    bytes_to_mib(stats.end_rss),
                    bytes_to_mib(stats.peak_rss),
                    bytes_to_mib(rss_delta),
                    stats.error or "",
                ]
            )
        else:
            status = "skipped" if node_id in processor.skipped_nodes else "not_executed"
            rows.append(
                [
                    node_id,
                    pipeline_node.name,
                    status,
                    "n/a",
                    "n/a",
                    "n/a",
                    "n/a",
                    "n/a",
                    "",
                ]
            )
    return rows


def _build_metadata_human(
    *,
    task: TaskInternal,
    recorder: BenchmarkRecorder,
    ordered_nodes: list[str],
) -> list[str]:
    lines: list[str] = ["", "Node output metadata (human-readable):"]
    for node_id in ordered_nodes:
        node_name = resolve_node_name(task, recorder.node_stats.get(node_id), node_id)
        meta = recorder.node_metadata.get(node_id)
        lines.append(f"Node {node_id} ({node_name}):")
        if not meta:
            lines.append("  (metadata not collected)")
            continue
        for output_name, output_meta in meta.items():
            lines.append(f"  Output: {output_name}")
            if output_meta is None:
                lines.append("    (none)")
                continue
            payload = dumps_metadata(output_meta, indent=2)
            lines.extend(["    " + line for line in payload.splitlines()])
    return lines


def _build_metadata_llm(*, recorder: BenchmarkRecorder, ordered_nodes: list[str]) -> list[str]:
    payload = {
        node_id: {
            output_name: serialize_metadata(meta)
            for output_name, meta in (recorder.node_metadata.get(node_id) or {}).items()
        }
        for node_id in ordered_nodes
    }
    return ["", "LLM Metadata (JSON):", json.dumps(payload, indent=2)]


def build_report(
    *,
    task: TaskInternal,
    processor: PipelineProcessor,
    recorder: BenchmarkRecorder,
    success: bool,
    include_metadata: bool,
) -> str:
    task_stats = recorder.task_stats
    duration_value = duration_s(task_stats.start_time, task_stats.end_time)
    overall_delta = None
    if task_stats.start_rss is not None and task_stats.end_rss is not None:
        overall_delta = task_stats.end_rss - task_stats.start_rss

    ordered_nodes = node_order(task=task, processor=processor)
    rows = _build_node_rows(
        task=task,
        processor=processor,
        recorder=recorder,
        ordered_nodes=ordered_nodes,
    )

    headers = [
        "node_id",
        "node_name",
        "status",
        "duration_s",
        "rss_start",
        "rss_end",
        "rss_peak",
        "rss_delta",
        "notes",
    ]

    summary = build_report_payload(
        task=task,
        processor=processor,
        recorder=recorder,
        success=success,
        ordered_nodes=ordered_nodes,
        include_metadata=include_metadata,
    )

    lines = [
        "Memory Benchmark Report",
        f"Task ID: {task.task_id}",
        f"Project ID: {task.project_id}",
        f"Status: {'success' if success else 'error'}",
        f"Duration: {duration_value} s",
        f"RSS start: {bytes_to_mib(task_stats.start_rss)}",
        f"RSS end: {bytes_to_mib(task_stats.end_rss)}",
        f"RSS peak: {bytes_to_mib(task_stats.peak_rss)}",
        f"RSS delta: {bytes_to_mib(overall_delta)}",
        "",
        "Per-node memory usage (RSS):",
        format_table(headers, rows),
        "",
        "LLM Summary (JSON):",
        json.dumps(summary, indent=2),
    ]
    if task_stats.error:
        lines.insert(5, f"Task error: {task_stats.error}")

    if include_metadata:
        lines.extend(_build_metadata_human(task=task, recorder=recorder, ordered_nodes=ordered_nodes))
        lines.extend(_build_metadata_llm(recorder=recorder, ordered_nodes=ordered_nodes))

    return "\n".join(lines)
