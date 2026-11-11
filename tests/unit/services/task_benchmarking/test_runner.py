import json
from pathlib import Path

from services.task_benchmarking.cli import parse_args
from services.task_benchmarking.runner import run_benchmark_once, run_matrix_benchmark

SAMPLE_PIPELINE = "services/task_benchmarking/pipelines/examples/sample_pipeline.json"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_sample_pipeline_run_reports_rows_and_matches_schemas(
    benchmark_registry,
    schema_errors,
    tmp_path: Path,
) -> None:
    options = parse_args(
        ["--pipeline", SAMPLE_PIPELINE, "--output-root", str(tmp_path), "--run-id", "sample"]
    )

    assert run_benchmark_once(options) == 0

    run_dir = tmp_path / "sample"
    report = _read_json(run_dir / "report.json")
    nodes = {node["node_id"]: node for node in report["report"]["nodes"]}
    assert report["report"]["rows_total"] == 200_000
    assert nodes["materialize"]["metrics"]["rows"] == 200_000
    assert nodes["materialize"]["rows_per_s"] > 0
    assert report["report"]["cpu_user_s"] is not None
    assert schema_errors(report, "benchmark_report.schema.json") == []
    assert schema_errors(_read_json(run_dir / "config.json"), "benchmark_run.schema.json") == []


def test_validate_only_and_matrix_artifacts_match_schemas(schema_errors, tmp_path: Path) -> None:
    matrix_path = tmp_path / "matrix.json"
    matrix_path.write_text(
        json.dumps({"cases": [{"name": "sample", "pipeline": SAMPLE_PIPELINE}]}),
        encoding="utf-8",
    )
    output_root = tmp_path / "runs"
    options = parse_args(
        [
            "--pipeline",
            SAMPLE_PIPELINE,
            "--output-root",
            str(output_root),
            "--run-id",
            "matrix",
            "--matrix",
            str(matrix_path),
            "--validate-only",
        ]
    )

    assert run_matrix_benchmark(options) == 0

    matrix_report = _read_json(output_root / "matrix" / "matrix_report.json")
    case_dir = output_root / "matrix_sample"
    assert schema_errors(matrix_report, "benchmark_report.schema.json") == []
    assert schema_errors(_read_json(case_dir / "report.json"), "benchmark_report.schema.json") == []
    assert schema_errors(_read_json(case_dir / "config.json"), "benchmark_run.schema.json") == []
    # The conditional schema still requires pipeline_path for non-matrix reports.
    assert schema_errors(
        {"schema_version": "1.0", "run_id": "x", "mode": "single", "status": "success"},
        "benchmark_report.schema.json",
    ) == ["$: missing required 'pipeline_path'"]
