from __future__ import annotations

import datetime as dt
import itertools
import json
import os
import platform
import re
import sys
import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal, Optional

from src.modules.pipeline_graph.infra.mappers.graph_edges import to_persistent as edge_to_persistent
from src.modules.pipeline_graph.infra.mappers.graph_nodes import to_persistent as node_to_persistent
from src.modules.pipeline_graph.infra.schemas.graph_edge import GraphEdgeUISchema
from src.modules.pipeline_graph.infra.schemas.graph_node import GraphNodeUISchema
from src.pipeline.execution_mode import PipelineExecutionMode
from src.pipeline.graph import build_pipeline_from_graph
from src.schemas.internal import TaskInternal


@dataclass(slots=True)
class RunPaths:
    run_id: str
    run_dir: str
    report_text_path: str
    report_json_path: str
    config_path: str
    env_path: str


PipelineFormat = Literal["auto", "internal", "ui_graph"]


def bytes_to_mib(value: int | None) -> str:
    if value is None:
        return "n/a"
    return f"{value / (1024 * 1024):.2f} MiB"


def duration_s(start: float | None, end: float | None) -> str:
    if start is None or end is None:
        return "n/a"
    return f"{end - start:.3f}"


def format_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    def _format_row(values: list[str]) -> str:
        return " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(values))

    sep = "-+-".join("-" * width for width in widths)
    lines = [_format_row(headers), sep]
    lines.extend(_format_row(row) for row in rows)
    return "\n".join(lines)


def load_pipeline(path: str, *, pipeline_format: PipelineFormat = "auto") -> dict[str, Any]:
    resolved_path = resolve_pipeline_path(path)
    with open(resolved_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Pipeline JSON must be an object with node_id keys.")
    resolved_format = detect_pipeline_format(payload, pipeline_format=pipeline_format)
    if resolved_format == "ui_graph":
        return _convert_ui_pipeline(payload)
    return payload


def detect_pipeline_format(payload: dict[str, Any], *, pipeline_format: PipelineFormat) -> PipelineFormat:
    if pipeline_format == "auto":
        if _looks_like_ui_pipeline(payload):
            return "ui_graph"
        return "internal"
    if pipeline_format == "ui_graph" and not _looks_like_ui_pipeline(payload):
        raise ValueError("Pipeline format is set to ui_graph, but payload has no 'nodes' array.")
    if pipeline_format == "internal" and _looks_like_ui_pipeline(payload):
        raise ValueError("Pipeline format is set to internal, but payload looks like UI graph JSON.")
    return pipeline_format


def resolve_pipeline_path(path: str) -> str:
    if os.path.isfile(path):
        return path
    fallback = _resolve_legacy_pipeline_path(path)
    if fallback:
        return fallback
    raise FileNotFoundError(f"Pipeline file not found: {path}")


def _resolve_legacy_pipeline_path(path: str) -> Optional[str]:
    filename = os.path.basename(path)
    if not filename:
        return None
    pipelines_root = os.path.join(os.path.dirname(__file__), "pipelines")
    if not os.path.isdir(pipelines_root):
        return None
    for root, _, files in os.walk(pipelines_root):
        if filename in files:
            return os.path.join(root, filename)
    return None


def _looks_like_ui_pipeline(payload: dict[str, Any]) -> bool:
    nodes = payload.get("nodes")
    return isinstance(nodes, list)


def _convert_ui_pipeline(payload: dict[str, Any]) -> dict[str, Any]:
    project_id = payload.get("projectId") or payload.get("project_id") or "memory-benchmark"
    user_id = payload.get("userId") or payload.get("user_id") or "memory-benchmark"

    raw_nodes = payload.get("nodes") or []
    raw_edges = payload.get("edges") or []

    nodes = [
        node_to_persistent(
            GraphNodeUISchema.model_validate(item),
            project_id=project_id,
            user_id=user_id,
        )
        for item in raw_nodes
    ]
    edges = [
        edge_to_persistent(
            GraphEdgeUISchema.model_validate(item),
            project_id=project_id,
            user_id=user_id,
        )
        for item in raw_edges
    ]
    return build_pipeline_from_graph(nodes=nodes, edges=edges)


def build_task(
    pipeline: dict[str, Any],
    outputs: list[str],
    user_id: str,
    exec_mode: str = "full",
) -> TaskInternal:
    payload = {
        "project_id": "memory-benchmark",
        "task_id": str(uuid.uuid4()),
        "user_id": user_id,
        "pipeline": pipeline,
        "target_nodes": outputs,
        "mode": PipelineExecutionMode(exec_mode),
        "send_ws_messages": False,
        "project_settings": {},
        "project_variables": {},
    }
    return TaskInternal.model_validate(payload)


def resolve_user_id(user_id: Optional[str]) -> str:
    resolved = user_id or os.getenv("TASK_BENCHMARKING_USER_ID")
    return resolved or "memory-benchmark"


def validate_requested_outputs(pipeline: dict[str, Any], outputs: list[str]) -> None:
    if not outputs:
        return
    missing = [node_id for node_id in outputs if node_id not in pipeline]
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Unknown output node id(s): {missing_list}")


def apply_input_overrides(
    pipeline: dict[str, Any],
    *,
    global_overrides: dict[str, Any],
    node_overrides: Optional[dict[str, dict[str, Any]]] = None,
) -> dict[str, Any]:
    if not global_overrides and not node_overrides:
        return pipeline
    patched = deepcopy(pipeline)
    for node_id, node_payload in patched.items():
        inputs = _node_inputs(node_payload)
        if inputs is None:
            continue
        for input_name, value in global_overrides.items():
            if input_name in inputs:
                inputs[input_name] = _updated_input_payload(inputs[input_name], value)
    if node_overrides:
        for node_id, input_values in node_overrides.items():
            node_payload = patched.get(node_id)
            if node_payload is None:
                continue
            inputs = _node_inputs(node_payload)
            if inputs is None:
                continue
            for input_name, value in input_values.items():
                if input_name in inputs:
                    inputs[input_name] = _updated_input_payload(inputs[input_name], value)
    return patched


def _node_inputs(node_payload: Any) -> Optional[dict[str, Any]]:
    if not isinstance(node_payload, dict):
        return None
    inputs = node_payload.get("inputs")
    if not isinstance(inputs, dict):
        return None
    return inputs


def _updated_input_payload(existing: Any, value: Any) -> Any:
    if isinstance(existing, dict):
        dvt_type = existing.get("__dvt_type")
        if dvt_type:
            if dvt_type == "const":
                payload = dict(existing)
                payload["value"] = value
                return payload
            return {"__dvt_type": "const", "value": value}
    return value


def combine_node_overrides(entries: list[tuple[str, str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for node_id, input_name, value in entries:
        node_mapping = result.setdefault(node_id, {})
        node_mapping[input_name] = value
    return result


def cartesian_parameter_grid(parameters: dict[str, list[Any]]) -> list[dict[str, Any]]:
    if not parameters:
        return [{}]
    keys = sorted(parameters)
    values = [parameters[key] for key in keys]
    grid: list[dict[str, Any]] = []
    for combination in itertools.product(*values):
        grid.append({key: value for key, value in zip(keys, combination, strict=False)})
    return grid


def prepare_run_paths(
    *,
    pipeline_path: str,
    output_root: str,
    run_id: Optional[str],
    report_text_path: Optional[str],
    report_json_path: Optional[str],
) -> RunPaths:
    resolved_run_id = sanitize_run_id(run_id) if run_id else generate_run_id(pipeline_path)
    run_dir = os.path.abspath(os.path.join(output_root, resolved_run_id))
    os.makedirs(run_dir, exist_ok=True)
    resolved_report_text = os.path.abspath(report_text_path) if report_text_path else os.path.join(
        run_dir, "report.txt"
    )
    resolved_report_json = os.path.abspath(report_json_path) if report_json_path else os.path.join(
        run_dir, "report.json"
    )
    return RunPaths(
        run_id=resolved_run_id,
        run_dir=run_dir,
        report_text_path=resolved_report_text,
        report_json_path=resolved_report_json,
        config_path=os.path.join(run_dir, "config.json"),
        env_path=os.path.join(run_dir, "env.txt"),
    )


def sanitize_run_id(run_id: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "-", run_id).strip(".-_")
    return sanitized or "run"


def generate_run_id(pipeline_path: str) -> str:
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%S")
    pipeline_name = os.path.splitext(os.path.basename(pipeline_path))[0] or "pipeline"
    pipeline_slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", pipeline_name).strip("-").lower()
    if not pipeline_slug:
        pipeline_slug = "pipeline"
    return f"{timestamp}_{pipeline_slug}"


def write_json_file(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def write_text_file(path: str, payload: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(payload)


def build_env_snapshot() -> str:
    lines = [
        f"timestamp_utc={dt.datetime.now(dt.UTC).isoformat()}",
        f"python={sys.version.replace(os.linesep, ' ')}",
        f"platform={platform.platform()}",
    ]
    for key in sorted(os.environ):
        lines.append(f"{key}={os.environ[key]}")
    return "\n".join(lines) + "\n"
