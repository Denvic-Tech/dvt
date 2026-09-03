from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from .utils import cartesian_parameter_grid, sanitize_run_id


@dataclass(slots=True)
class MatrixPipeline:
    path: str
    name: str
    pipeline_format: str


@dataclass(slots=True)
class MatrixCase:
    name: str
    pipeline: MatrixPipeline
    overrides: dict[str, Any]
    node_overrides: dict[str, dict[str, Any]]


def load_matrix_cases(
    *,
    matrix_path: str,
    default_pipeline: str,
    default_pipeline_format: str,
) -> list[MatrixCase]:
    payload = _load_matrix_payload(matrix_path)
    pipelines = _parse_pipelines(
        payload=payload,
        default_pipeline=default_pipeline,
        default_pipeline_format=default_pipeline_format,
    )

    generated_cases = _build_generated_cases(payload, pipelines)
    explicit_cases = _build_explicit_cases(payload, pipelines)
    cases = [*generated_cases, *explicit_cases]
    if not cases:
        raise ValueError("Matrix config produced no cases.")
    return _deduplicate_case_names(cases)


def _load_matrix_payload(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        raw_text = handle.read()
    if not raw_text.strip():
        raise ValueError(f"Matrix config is empty: {path}")

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        payload = _load_yaml_payload(raw_text, path)

    if not isinstance(payload, dict):
        raise ValueError("Matrix config root must be an object.")
    return payload


def _load_yaml_payload(raw_text: str, path: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise ValueError(
            f"Matrix file is not valid JSON and PyYAML is unavailable: {path}"
        ) from exc
    payload = yaml.safe_load(raw_text)
    if not isinstance(payload, dict):
        raise ValueError("YAML matrix config root must be an object.")
    return payload


def _parse_pipelines(
    *,
    payload: dict[str, Any],
    default_pipeline: str,
    default_pipeline_format: str,
) -> list[MatrixPipeline]:
    raw_pipelines = payload.get("pipelines")
    if raw_pipelines is None:
        return [
            MatrixPipeline(
                path=default_pipeline,
                name=sanitize_run_id(default_pipeline.split("/")[-1].split(".")[0]),
                pipeline_format=default_pipeline_format,
            )
        ]
    if not isinstance(raw_pipelines, list) or not raw_pipelines:
        raise ValueError("'pipelines' must be a non-empty list when provided.")

    parsed: list[MatrixPipeline] = []
    for item in raw_pipelines:
        if isinstance(item, str):
            name = sanitize_run_id(item.split("/")[-1].split(".")[0])
            parsed.append(
                MatrixPipeline(
                    path=item,
                    name=name,
                    pipeline_format=default_pipeline_format,
                )
            )
            continue
        if isinstance(item, dict):
            path = item.get("path")
            if not isinstance(path, str) or not path:
                raise ValueError("Pipeline item object must contain non-empty string 'path'.")
            name_raw = item.get("name")
            name = sanitize_run_id(name_raw) if isinstance(name_raw, str) and name_raw else sanitize_run_id(
                path.split("/")[-1].split(".")[0]
            )
            pipeline_format = item.get("pipeline_format") or default_pipeline_format
            parsed.append(
                MatrixPipeline(
                    path=path,
                    name=name,
                    pipeline_format=str(pipeline_format),
                )
            )
            continue
        raise ValueError("Each pipeline entry must be either string or object.")
    return parsed


def _build_generated_cases(payload: dict[str, Any], pipelines: list[MatrixPipeline]) -> list[MatrixCase]:
    raw_parameters = payload.get("parameters") or {}
    if not isinstance(raw_parameters, dict):
        raise ValueError("'parameters' must be an object when provided.")

    normalized_parameters: dict[str, list[Any]] = {}
    for key, value in raw_parameters.items():
        if isinstance(value, list):
            if not value:
                raise ValueError(f"Parameter '{key}' has empty values list.")
            normalized_parameters[key] = value
        else:
            normalized_parameters[key] = [value]

    if not normalized_parameters:
        return []

    grid = cartesian_parameter_grid(normalized_parameters)
    generated: list[MatrixCase] = []
    for pipeline in pipelines:
        for combo in grid:
            suffix = "_".join(f"{sanitize_run_id(key)}-{sanitize_run_id(str(value))}" for key, value in combo.items())
            case_name = sanitize_run_id(f"{pipeline.name}_{suffix}")
            generated.append(
                MatrixCase(
                    name=case_name,
                    pipeline=pipeline,
                    overrides=combo,
                    node_overrides={},
                )
            )
    return generated


def _build_explicit_cases(payload: dict[str, Any], pipelines: list[MatrixPipeline]) -> list[MatrixCase]:
    raw_cases = payload.get("cases")
    if raw_cases is None:
        return []
    if not isinstance(raw_cases, list):
        raise ValueError("'cases' must be a list when provided.")

    by_name = {pipeline.name: pipeline for pipeline in pipelines}
    explicit: list[MatrixCase] = []
    for index, item in enumerate(raw_cases, start=1):
        if not isinstance(item, dict):
            raise ValueError("Each case item must be an object.")

        pipeline_name = item.get("pipeline_name")
        pipeline_path = item.get("pipeline")
        pipeline: Optional[MatrixPipeline] = None
        if isinstance(pipeline_name, str) and pipeline_name:
            pipeline = by_name.get(pipeline_name)
            if pipeline is None:
                raise ValueError(f"Case references unknown pipeline_name: {pipeline_name}")
        elif isinstance(pipeline_path, str) and pipeline_path:
            pipeline = MatrixPipeline(
                path=pipeline_path,
                name=sanitize_run_id(pipeline_path.split("/")[-1].split(".")[0]),
                pipeline_format=str(item.get("pipeline_format") or "auto"),
            )
        else:
            pipeline = pipelines[0]

        raw_name = item.get("name")
        default_name = f"{pipeline.name}_case-{index}"
        case_name = sanitize_run_id(raw_name) if isinstance(raw_name, str) and raw_name else sanitize_run_id(
            default_name
        )

        raw_overrides = item.get("overrides") or {}
        if not isinstance(raw_overrides, dict):
            raise ValueError("Case 'overrides' must be an object.")

        raw_node_overrides = item.get("node_overrides") or {}
        if not isinstance(raw_node_overrides, dict):
            raise ValueError("Case 'node_overrides' must be an object.")

        parsed_node_overrides: dict[str, dict[str, Any]] = {}
        for node_id, values in raw_node_overrides.items():
            if not isinstance(values, dict):
                raise ValueError("node_overrides values must be objects with input->value pairs.")
            parsed_node_overrides[str(node_id)] = {str(k): v for k, v in values.items()}

        explicit.append(
            MatrixCase(
                name=case_name,
                pipeline=pipeline,
                overrides={str(k): v for k, v in raw_overrides.items()},
                node_overrides=parsed_node_overrides,
            )
        )
    return explicit


def _deduplicate_case_names(cases: list[MatrixCase]) -> list[MatrixCase]:
    seen: dict[str, int] = {}
    deduplicated: list[MatrixCase] = []
    for case in cases:
        count = seen.get(case.name, 0)
        seen[case.name] = count + 1
        if count == 0:
            deduplicated.append(case)
            continue
        deduplicated.append(
            MatrixCase(
                name=sanitize_run_id(f"{case.name}_{count + 1}"),
                pipeline=case.pipeline,
                overrides=case.overrides,
                node_overrides=case.node_overrides,
            )
        )
    return deduplicated
