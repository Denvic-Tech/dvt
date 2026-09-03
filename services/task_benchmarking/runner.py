from __future__ import annotations

import asyncio
import gc
import os
import time
from dataclasses import replace
from typing import Any, Optional

import psutil

from src.pipeline import PipelineProcessor

from .cli import BenchmarkOptions
from .config import cli_global_input_overrides, merge_global_overrides, resolve_preset
from .matrix import load_matrix_cases
from .recorder import BenchmarkRecorder
from .report import build_report, build_report_payload
from .utils import (
    apply_input_overrides,
    build_env_snapshot,
    build_task,
    bytes_to_mib,
    duration_s,
    generate_run_id,
    load_pipeline,
    prepare_run_paths,
    resolve_pipeline_path,
    resolve_user_id,
    sanitize_run_id,
    validate_requested_outputs,
    write_json_file,
    write_text_file,
)

REPORT_SCHEMA_VERSION = "1.0"
DEFAULT_SAMPLE_INTERVAL = 0.1


async def run_pipeline(
    task,
    recorder: BenchmarkRecorder,
    include_metadata: bool,
) -> tuple[bool, str, dict[str, Any]]:
    processor = PipelineProcessor(
        task=task,
        on_task_started=recorder.on_task_started,
        on_task_success=recorder.on_task_success,
        on_task_error=recorder.on_task_error,
        on_task_canceled=recorder.on_task_canceled,
        on_node_process_start=recorder.on_node_start,
        on_node_process_success=recorder.on_node_success,
        on_node_error=recorder.on_node_error,
        on_node_metadata=recorder.on_node_metadata,
    )
    result = await processor.process()
    report_text = build_report(
        task=task,
        processor=processor,
        recorder=recorder,
        success=result.success,
        include_metadata=include_metadata,
    )
    report_payload = build_report_payload(
        task=task,
        processor=processor,
        recorder=recorder,
        success=result.success,
        include_metadata=include_metadata,
    )
    return result.success, report_text, report_payload


def _resolve_effective_sample_interval(options: BenchmarkOptions) -> float:
    preset = resolve_preset(options.preset)
    if preset is None or preset.sample_interval is None:
        return options.sample_interval
    if options.sample_interval != DEFAULT_SAMPLE_INTERVAL:
        return options.sample_interval
    return preset.sample_interval


def _resolve_global_overrides(
    options: BenchmarkOptions,
    *,
    extra_global_overrides: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    preset = resolve_preset(options.preset)
    preset_overrides = preset.global_input_overrides if preset else {}
    return merge_global_overrides(
        preset_overrides,
        cli_global_input_overrides(
            npartitions=options.npartitions,
            num_workers=options.num_workers,
            max_rows_per_partition=options.max_rows_per_partition,
        ),
        extra_global_overrides or {},
    )


def _build_run_config(
    *,
    options: BenchmarkOptions,
    resolved_pipeline_path: str,
    pipeline_format: str,
    run_id: str,
    user_id: str,
    sample_interval: float,
    global_overrides: dict[str, Any],
    node_overrides: Optional[dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": run_id,
        "pipeline_path": resolved_pipeline_path,
        "pipeline_format": pipeline_format,
        "user_id": user_id,
        "options": {
            "outputs": options.outputs,
            "sample_interval": sample_interval,
            "repeat": options.repeat,
            "repeat_include_reports": options.repeat_include_reports,
            "include_metadata": options.include_metadata,
            "exec_mode": options.exec_mode,
            "validate_only": options.validate_only,
            "dry_run": options.dry_run,
            "preset": options.preset,
            "patches": options.patches,
            "global_input_overrides": global_overrides,
            "node_overrides": node_overrides or {},
        },
    }


def _build_single_run_json(
    *,
    run_id: str,
    resolved_pipeline_path: str,
    success: bool,
    report_payload: dict[str, Any],
    mode: str = "single",
) -> dict[str, Any]:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": run_id,
        "mode": mode,
        "pipeline_path": resolved_pipeline_path,
        "status": "success" if success else "error",
        "report": report_payload,
    }


def _write_run_context(config_payload: dict[str, Any], env_snapshot: str, config_path: str, env_path: str) -> None:
    write_json_file(config_path, config_payload)
    write_text_file(env_path, env_snapshot)


def _write_final_reports(
    *,
    report_text: str,
    report_json_payload: dict[str, Any],
    report_text_path: str,
    report_json_path: str,
) -> None:
    write_text_file(report_text_path, report_text)
    write_json_file(report_json_path, report_json_payload)


def run_benchmark_once(
    options: BenchmarkOptions,
    *,
    pipeline_path_override: Optional[str] = None,
    pipeline_format_override: Optional[str] = None,
    run_id_override: Optional[str] = None,
    extra_global_overrides: Optional[dict[str, Any]] = None,
    node_overrides: Optional[dict[str, dict[str, Any]]] = None,
) -> int:
    effective_pipeline_path = pipeline_path_override or options.pipeline
    effective_pipeline_format = pipeline_format_override or options.pipeline_format
    resolved_pipeline_path = resolve_pipeline_path(effective_pipeline_path)
    user_id = resolve_user_id(options.user_id)
    sample_interval = _resolve_effective_sample_interval(options)
    global_overrides = _resolve_global_overrides(options, extra_global_overrides=extra_global_overrides)

    run_paths = prepare_run_paths(
        pipeline_path=resolved_pipeline_path,
        output_root=options.output_root,
        run_id=run_id_override or options.run_id,
        report_text_path=options.report,
        report_json_path=options.report_json,
    )

    pipeline = load_pipeline(resolved_pipeline_path, pipeline_format=effective_pipeline_format)
    pipeline = apply_input_overrides(
        pipeline,
        global_overrides=global_overrides,
        node_overrides=node_overrides,
    )
    validate_requested_outputs(pipeline, options.outputs)
    config_payload = _build_run_config(
        options=options,
        resolved_pipeline_path=resolved_pipeline_path,
        pipeline_format=effective_pipeline_format,
        run_id=run_paths.run_id,
        user_id=user_id,
        sample_interval=sample_interval,
        global_overrides=global_overrides,
        node_overrides=node_overrides,
    )
    _write_run_context(
        config_payload=config_payload,
        env_snapshot=build_env_snapshot(),
        config_path=run_paths.config_path,
        env_path=run_paths.env_path,
    )

    if options.dry_run or options.validate_only:
        mode = "dry_run" if options.dry_run else "validate_only"
        summary_title = "Memory Benchmark Dry Run" if options.dry_run else "Memory Benchmark Validation"
        validation_payload = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "run_id": run_paths.run_id,
            "mode": mode,
            "pipeline_path": resolved_pipeline_path,
            "status": "success",
            "validation": {
                "nodes": len(pipeline),
                "outputs_requested": options.outputs,
                "user_id": user_id,
                "pipeline_format": effective_pipeline_format,
                "sample_interval": sample_interval,
                "global_input_overrides": global_overrides,
                "node_overrides": node_overrides or {},
                "preset": options.preset,
            },
        }
        validation_report = "\n".join(
            [
                summary_title,
                "Status: success",
                f"Pipeline: {resolved_pipeline_path}",
                f"Pipeline format: {effective_pipeline_format}",
                f"Nodes: {len(pipeline)}",
                f"Outputs requested: {', '.join(options.outputs) if options.outputs else '(all)'}",
                f"Preset: {options.preset or '(none)'}",
                f"Global overrides: {global_overrides or '(none)'}",
                f"Artifacts: {run_paths.run_dir}",
            ]
        )
        print(validation_report)
        _write_final_reports(
            report_text=validation_report,
            report_json_payload=validation_payload,
            report_text_path=run_paths.report_text_path,
            report_json_path=run_paths.report_json_path,
        )
        return 0

    if options.repeat <= 1:
        task = build_task(
            pipeline=pipeline,
            outputs=options.outputs,
            user_id=user_id,
            exec_mode=options.exec_mode,
        )
        recorder = BenchmarkRecorder(
            sample_interval_sec=sample_interval,
            collect_metadata=options.include_metadata,
        )

        success, report_text, report_payload = asyncio.run(
            run_pipeline(task=task, recorder=recorder, include_metadata=options.include_metadata)
        )
        print(report_text)
        _write_final_reports(
            report_text=report_text,
            report_json_payload=_build_single_run_json(
                run_id=run_paths.run_id,
                resolved_pipeline_path=resolved_pipeline_path,
                success=success,
                report_payload=report_payload,
            ),
            report_text_path=run_paths.report_text_path,
            report_json_path=run_paths.report_json_path,
        )
        print(f"Artifacts saved to: {run_paths.run_dir}")
        return 0 if success else 1

    process = psutil.Process()
    results: list[dict[str, Any]] = []
    overall_success = True

    for run_idx in range(1, options.repeat + 1):
        gc.collect()
        time.sleep(0.1)
        rss_start = int(process.memory_info().rss)

        task = build_task(
            pipeline=pipeline,
            outputs=options.outputs,
            user_id=user_id,
            exec_mode=options.exec_mode,
        )
        recorder = BenchmarkRecorder(
            sample_interval_sec=sample_interval,
            collect_metadata=options.include_metadata,
        )
        success, report_text, report_payload = asyncio.run(
            run_pipeline(task=task, recorder=recorder, include_metadata=options.include_metadata)
        )

        rss_end = int(process.memory_info().rss)
        rss_peak = recorder.task_stats.peak_rss or rss_end
        duration_value = None
        if recorder.task_stats.start_time is not None and recorder.task_stats.end_time is not None:
            duration_value = recorder.task_stats.end_time - recorder.task_stats.start_time

        results.append(
            {
                "run": run_idx,
                "success": success,
                "rss_start": rss_start,
                "rss_end": rss_end,
                "rss_peak": rss_peak,
                "duration": duration_s(recorder.task_stats.start_time, recorder.task_stats.end_time),
                "duration_s": duration_value,
                "report_text": report_text,
                "report": report_payload,
            }
        )
        overall_success = overall_success and success

    lines = [
        "Memory Leak Check",
        f"Runs: {options.repeat}",
        f"Pipeline: {resolved_pipeline_path}",
        "",
        "run | status | duration_s | rss_start | rss_end | rss_peak | rss_delta",
        "----+--------+------------+-----------+---------+----------+----------",
    ]

    for item in results:
        delta = item["rss_end"] - item["rss_start"]
        lines.append(
            f"{item['run']:>3} | "
            f"{('ok' if item['success'] else 'fail'):>6} | "
            f"{item['duration']:>10} | "
            f"{bytes_to_mib(item['rss_start']):>9} | "
            f"{bytes_to_mib(item['rss_end']):>7} | "
            f"{bytes_to_mib(item['rss_peak']):>8} | "
            f"{bytes_to_mib(delta):>8}"
        )

    if options.repeat_include_reports:
        lines.append("")
        lines.append("Per-run reports:")
        for item in results:
            lines.append("")
            lines.append(f"=== Run {item['run']} ===")
            lines.append(item["report_text"])

    report_text = "\n".join(lines)
    report_json_payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": run_paths.run_id,
        "mode": "repeat",
        "pipeline_path": resolved_pipeline_path,
        "repeat": options.repeat,
        "status": "success" if overall_success else "error",
        "runs": [
            {
                "run": item["run"],
                "status": "success" if item["success"] else "error",
                "duration_s": item["duration_s"],
                "rss_start_bytes": item["rss_start"],
                "rss_end_bytes": item["rss_end"],
                "rss_peak_bytes": item["rss_peak"],
                "rss_delta_bytes": item["rss_end"] - item["rss_start"],
                "report": item["report"],
            }
            for item in results
        ],
    }

    print(report_text)
    _write_final_reports(
        report_text=report_text,
        report_json_payload=report_json_payload,
        report_text_path=run_paths.report_text_path,
        report_json_path=run_paths.report_json_path,
    )
    print(f"Artifacts saved to: {run_paths.run_dir}")
    return 0 if overall_success else 1


def run_matrix_benchmark(options: BenchmarkOptions) -> int:
    if not options.matrix:
        raise ValueError("--matrix path is required for matrix mode.")

    cases = load_matrix_cases(
        matrix_path=options.matrix,
        default_pipeline=options.pipeline,
        default_pipeline_format=options.pipeline_format,
    )

    matrix_run_id = sanitize_run_id(options.run_id) if options.run_id else sanitize_run_id(
        f"{generate_run_id(options.pipeline)}_matrix"
    )
    matrix_dir = os.path.abspath(os.path.join(options.output_root, matrix_run_id))
    os.makedirs(matrix_dir, exist_ok=True)

    summary_rows: list[dict[str, Any]] = []
    overall_success = True
    for index, case in enumerate(cases, start=1):
        case_run_id = sanitize_run_id(f"{matrix_run_id}_{case.name}")
        print(f"=== Matrix case {index}/{len(cases)}: {case.name} ===")
        case_options = replace(
            options,
            matrix=None,
            report=None,
            report_json=None,
            run_id=case_run_id,
            patches=[],
            compare_candidate_python=None,
            compare_candidate_workdir=None,
            compare_candidate_pipeline=None,
        )
        exit_code = run_benchmark_once(
            case_options,
            pipeline_path_override=case.pipeline.path,
            pipeline_format_override=case.pipeline.pipeline_format,
            run_id_override=case_run_id,
            extra_global_overrides=case.overrides,
            node_overrides=case.node_overrides,
        )
        case_report_path = os.path.join(os.path.abspath(options.output_root), case_run_id, "report.json")
        summary_rows.append(
            {
                "case": case.name,
                "pipeline": case.pipeline.path,
                "pipeline_format": case.pipeline.pipeline_format,
                "overrides": case.overrides,
                "node_overrides": case.node_overrides,
                "status": "success" if exit_code == 0 else "error",
                "report_json": case_report_path,
            }
        )
        overall_success = overall_success and exit_code == 0

    summary_payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": matrix_run_id,
        "mode": "matrix",
        "status": "success" if overall_success else "error",
        "cases": summary_rows,
    }
    write_json_file(os.path.join(matrix_dir, "matrix_report.json"), summary_payload)

    lines = [
        "Memory Benchmark Matrix Report",
        f"Run ID: {matrix_run_id}",
        f"Status: {summary_payload['status']}",
        f"Cases: {len(summary_rows)}",
        "",
        "case | status | report_json",
        "-----+--------+------------",
    ]
    for row in summary_rows:
        lines.append(f"{row['case']} | {row['status']} | {row['report_json']}")
    report_text = "\n".join(lines)
    write_text_file(os.path.join(matrix_dir, "matrix_report.txt"), report_text)
    print(report_text)
    return 0 if overall_success else 1
