from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Optional

from .cli import BenchmarkOptions
from .utils import generate_run_id, sanitize_run_id, write_json_file, write_text_file


def resolve_patch_paths(patches: list[str]) -> list[str]:
    resolved: list[str] = []
    for patch in patches:
        path = os.path.abspath(patch)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Patch file not found: {patch}")
        resolved.append(path)
    return resolved


def run_git_apply(patch_path: str, reverse: bool) -> None:
    cmd = ["git", "apply", "--whitespace=nowarn"]
    if reverse:
        cmd.append("--reverse")
    cmd.append(patch_path)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip() or "Unknown git apply error."
        direction = "revert" if reverse else "apply"
        raise RuntimeError(f"Failed to {direction} patch {patch_path}: {details}")


def apply_git_patches(patches: list[str], reverse: bool) -> None:
    patch_order = list(reversed(patches)) if reverse else patches
    for patch_path in patch_order:
        run_git_apply(patch_path, reverse=reverse)


def paired_report_paths(
    path: Optional[str],
    *,
    first_suffix: str,
    second_suffix: str,
    fallback_ext: str,
) -> tuple[Optional[str], Optional[str]]:
    if not path:
        return None, None
    base, ext = os.path.splitext(path)
    if ext:
        return f"{base}.{first_suffix}{ext}", f"{base}.{second_suffix}{ext}"
    return f"{path}.{first_suffix}{fallback_ext}", f"{path}.{second_suffix}{fallback_ext}"


def build_subprocess_args(
    *,
    executable: str,
    pipeline: str,
    pipeline_format: str,
    exec_mode: str,
    outputs: list[str],
    sample_interval: float,
    repeat: int,
    repeat_include_reports: bool,
    report_text: Optional[str],
    report_json: Optional[str],
    output_root: str,
    run_id: Optional[str],
    user_id: Optional[str],
    include_metadata: bool,
    preset: Optional[str],
    npartitions: Optional[int],
    num_workers: Optional[int],
    max_rows_per_partition: Optional[int],
) -> list[str]:
    cmd = [
        executable,
        "-m",
        "services.task_benchmarking.main",
        "--_once",
        "--pipeline",
        pipeline,
        "--pipeline-format",
        pipeline_format,
        "--exec-mode",
        exec_mode,
        "--sample-interval",
        str(sample_interval),
    ]
    if outputs:
        cmd.extend(["--outputs", *outputs])
    if report_text:
        cmd.extend(["--report", report_text])
    if report_json:
        cmd.extend(["--report-json", report_json])
    cmd.extend(["--output-root", output_root])
    if run_id:
        cmd.extend(["--run-id", run_id])
    cmd.extend(["--repeat", str(repeat)])
    if repeat_include_reports:
        cmd.append("--repeat-include-reports")
    if user_id:
        cmd.extend(["--user-id", user_id])
    if include_metadata:
        cmd.append("--include-metadata")
    if preset:
        cmd.extend(["--preset", preset])
    if npartitions is not None:
        cmd.extend(["--npartitions", str(npartitions)])
    if num_workers is not None:
        cmd.extend(["--num-workers", str(num_workers)])
    if max_rows_per_partition is not None:
        cmd.extend(["--max-rows-per-partition", str(max_rows_per_partition)])
    return cmd


def run_subprocess(label: str, cmd: list[str], *, cwd: Optional[str] = None) -> tuple[int, str, str]:
    print(f"=== {label} ===")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    stdout = result.stdout.rstrip()
    stderr = result.stderr.rstrip()
    if stdout:
        print(stdout)
    if stderr:
        sys.stderr.write(f"{stderr}\n")
    return result.returncode, stdout, stderr


def run_with_patches(options: BenchmarkOptions) -> int:
    patches = resolve_patch_paths(options.patches)
    baseline_report_text, patched_report_text = paired_report_paths(
        options.report,
        first_suffix="baseline",
        second_suffix="patched",
        fallback_ext=".txt",
    )
    baseline_report_json, patched_report_json = paired_report_paths(
        options.report_json,
        first_suffix="baseline",
        second_suffix="patched",
        fallback_ext=".json",
    )
    run_prefix = sanitize_run_id(options.run_id) if options.run_id else sanitize_run_id(
        f"{generate_run_id(options.pipeline)}_patch"
    )
    baseline_run_id = f"{run_prefix}_baseline"
    patched_run_id = f"{run_prefix}_patched"

    print("WARNING: --patch mode mutates git state via git apply. Prefer safe compare mode when possible.")
    baseline_cmd = build_subprocess_args(
        executable=sys.executable,
        pipeline=options.pipeline,
        pipeline_format=options.pipeline_format,
        outputs=options.outputs,
        sample_interval=options.sample_interval,
        repeat=options.repeat,
        repeat_include_reports=options.repeat_include_reports,
        report_text=baseline_report_text,
        report_json=baseline_report_json,
        output_root=options.output_root,
        run_id=baseline_run_id,
        user_id=options.user_id,
        include_metadata=options.include_metadata,
        exec_mode=options.exec_mode,
        preset=options.preset,
        npartitions=options.npartitions,
        num_workers=options.num_workers,
        max_rows_per_partition=options.max_rows_per_partition,
    )
    baseline_code, _, _ = run_subprocess("Baseline (original code)", baseline_cmd)

    patched_code: int
    revert_error: Optional[Exception] = None
    try:
        print("Applying patches:")
        for patch in patches:
            print(f"- {patch}")
        apply_git_patches(patches, reverse=False)
        patched_cmd = build_subprocess_args(
            executable=sys.executable,
            pipeline=options.pipeline,
            pipeline_format=options.pipeline_format,
            outputs=options.outputs,
            sample_interval=options.sample_interval,
            repeat=options.repeat,
            repeat_include_reports=options.repeat_include_reports,
            report_text=patched_report_text,
            report_json=patched_report_json,
            output_root=options.output_root,
            run_id=patched_run_id,
            user_id=options.user_id,
            include_metadata=options.include_metadata,
            exec_mode=options.exec_mode,
            preset=options.preset,
            npartitions=options.npartitions,
            num_workers=options.num_workers,
            max_rows_per_partition=options.max_rows_per_partition,
        )
        patched_code, _, _ = run_subprocess("Patched code", patched_cmd)
    except Exception as exc:  # noqa: BLE001 - want to show failures and keep cleanup below
        sys.stderr.write(f"Patch run failed: {exc}\n")
        patched_code = 1
    finally:
        try:
            apply_git_patches(patches, reverse=True)
        except Exception as exc:  # noqa: BLE001 - ensure cleanup errors are visible
            revert_error = exc

    if revert_error:
        sys.stderr.write(f"Failed to revert patches cleanly: {revert_error}\n")
        return 1

    baseline_summary_report_json = baseline_report_json or os.path.join(
        os.path.abspath(options.output_root),
        baseline_run_id,
        "report.json",
    )
    patched_summary_report_json = patched_report_json or os.path.join(
        os.path.abspath(options.output_root),
        patched_run_id,
        "report.json",
    )
    _write_compare_summary(
        output_root=options.output_root,
        run_prefix=run_prefix,
        baseline_run_id=baseline_run_id,
        candidate_run_id=patched_run_id,
        baseline_report_json=baseline_summary_report_json,
        candidate_report_json=patched_summary_report_json,
        candidate_label="patched",
    )
    return 0 if baseline_code == 0 and patched_code == 0 else 1


def run_safe_compare(options: BenchmarkOptions) -> int:
    if not options.compare_candidate_python:
        raise ValueError("--compare-candidate-python is required for safe compare mode.")

    candidate_pipeline = options.compare_candidate_pipeline or options.pipeline
    candidate_workdir = options.compare_candidate_workdir
    run_prefix = sanitize_run_id(options.run_id) if options.run_id else sanitize_run_id(
        f"{generate_run_id(options.pipeline)}_compare"
    )
    baseline_run_id = f"{run_prefix}_baseline"
    candidate_run_id = f"{run_prefix}_candidate"

    baseline_report_text, candidate_report_text = paired_report_paths(
        options.report,
        first_suffix="baseline",
        second_suffix="candidate",
        fallback_ext=".txt",
    )
    baseline_report_json, candidate_report_json = paired_report_paths(
        options.report_json,
        first_suffix="baseline",
        second_suffix="candidate",
        fallback_ext=".json",
    )

    baseline_cmd = build_subprocess_args(
        executable=sys.executable,
        pipeline=options.pipeline,
        pipeline_format=options.pipeline_format,
        outputs=options.outputs,
        sample_interval=options.sample_interval,
        repeat=options.repeat,
        repeat_include_reports=options.repeat_include_reports,
        report_text=baseline_report_text,
        report_json=baseline_report_json,
        output_root=options.output_root,
        run_id=baseline_run_id,
        user_id=options.user_id,
        include_metadata=options.include_metadata,
        exec_mode=options.exec_mode,
        preset=options.preset,
        npartitions=options.npartitions,
        num_workers=options.num_workers,
        max_rows_per_partition=options.max_rows_per_partition,
    )
    baseline_code, _, _ = run_subprocess("Baseline", baseline_cmd)

    candidate_cmd = build_subprocess_args(
        executable=options.compare_candidate_python,
        pipeline=candidate_pipeline,
        pipeline_format=options.pipeline_format,
        outputs=options.outputs,
        sample_interval=options.sample_interval,
        repeat=options.repeat,
        repeat_include_reports=options.repeat_include_reports,
        report_text=candidate_report_text,
        report_json=candidate_report_json,
        output_root=options.output_root,
        run_id=candidate_run_id,
        user_id=options.user_id,
            include_metadata=options.include_metadata,
            exec_mode=options.exec_mode,
        preset=options.preset,
        npartitions=options.npartitions,
        num_workers=options.num_workers,
        max_rows_per_partition=options.max_rows_per_partition,
    )
    candidate_code, _, _ = run_subprocess("Candidate", candidate_cmd, cwd=candidate_workdir)

    baseline_summary_report_json = baseline_report_json or os.path.join(
        os.path.abspath(options.output_root),
        baseline_run_id,
        "report.json",
    )
    candidate_summary_report_json = candidate_report_json or os.path.join(
        os.path.abspath(options.output_root),
        candidate_run_id,
        "report.json",
    )
    _write_compare_summary(
        output_root=options.output_root,
        run_prefix=run_prefix,
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        baseline_report_json=baseline_summary_report_json,
        candidate_report_json=candidate_summary_report_json,
        candidate_label="candidate",
    )
    return 0 if baseline_code == 0 and candidate_code == 0 else 1


def _write_compare_summary(
    *,
    output_root: str,
    run_prefix: str,
    baseline_run_id: str,
    candidate_run_id: str,
    baseline_report_json: str,
    candidate_report_json: str,
    candidate_label: str,
) -> None:
    summary_dir = os.path.abspath(os.path.join(output_root, run_prefix))
    os.makedirs(summary_dir, exist_ok=True)

    baseline_payload = _read_json_if_exists(baseline_report_json)
    candidate_payload = _read_json_if_exists(candidate_report_json)

    baseline_metrics = _extract_summary_metrics(baseline_payload)
    candidate_metrics = _extract_summary_metrics(candidate_payload)
    diff = {
        "duration_s": _diff_metric(candidate_metrics.get("duration_s"), baseline_metrics.get("duration_s")),
        "rss_peak_bytes": _diff_metric(
            candidate_metrics.get("rss_peak_bytes"),
            baseline_metrics.get("rss_peak_bytes"),
        ),
    }

    payload = {
        "baseline_run_id": baseline_run_id,
        f"{candidate_label}_run_id": candidate_run_id,
        "baseline_report_json": baseline_report_json,
        f"{candidate_label}_report_json": candidate_report_json,
        "baseline_metrics": baseline_metrics,
        f"{candidate_label}_metrics": candidate_metrics,
        "delta": diff,
    }
    write_json_file(os.path.join(summary_dir, "compare_report.json"), payload)

    lines = [
        "Memory Benchmark Compare Report",
        f"Baseline: {baseline_run_id}",
        f"{candidate_label.capitalize()}: {candidate_run_id}",
        f"Baseline report: {baseline_report_json}",
        f"{candidate_label.capitalize()} report: {candidate_report_json}",
        f"Duration delta (s): {diff['duration_s']}",
        f"RSS peak delta (bytes): {diff['rss_peak_bytes']}",
    ]
    write_text_file(os.path.join(summary_dir, "compare_report.txt"), "\n".join(lines))


def _read_json_if_exists(path: str) -> Optional[dict[str, Any]]:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _extract_summary_metrics(payload: Optional[dict[str, Any]]) -> dict[str, Optional[float]]:
    if not payload:
        return {"duration_s": None, "rss_peak_bytes": None}

    mode = payload.get("mode")
    if mode == "single":
        report = payload.get("report") or {}
        overall = report.get("overall") or {}
        return {
            "duration_s": report.get("duration_s"),
            "rss_peak_bytes": overall.get("rss_peak_bytes"),
        }
    if mode == "repeat":
        runs = payload.get("runs")
        if not isinstance(runs, list) or not runs:
            return {"duration_s": None, "rss_peak_bytes": None}
        duration_values = [run.get("duration_s") for run in runs if isinstance(run, dict)]
        peak_values = [run.get("rss_peak_bytes") for run in runs if isinstance(run, dict)]
        duration_avg = _avg(duration_values)
        peak_avg = _avg(peak_values)
        return {
            "duration_s": duration_avg,
            "rss_peak_bytes": peak_avg,
        }
    return {"duration_s": None, "rss_peak_bytes": None}


def _avg(values: list[Any]) -> Optional[float]:
    normalized: list[float] = []
    for value in values:
        if isinstance(value, (int, float)):
            normalized.append(float(value))
    if not normalized:
        return None
    return sum(normalized) / len(normalized)


def _diff_metric(current: Optional[float], baseline: Optional[float]) -> Optional[float]:
    if current is None or baseline is None:
        return None
    return current - baseline
