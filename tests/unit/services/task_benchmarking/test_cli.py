from services.task_benchmarking.cli import parse_args


def test_parse_args_supports_new_options() -> None:
    options = parse_args(
        [
            "--pipeline",
            "services/task_benchmarking/pipelines/examples/sample_pipeline.json",
            "--report",
            "tmp/report.txt",
            "--report-json",
            "tmp/report.json",
            "--output-root",
            "tmp/task_benchmarking/runs",
            "--run-id",
            "run-1",
            "--pipeline-format",
            "internal",
            "--exec-mode",
            "metadata_only",
            "--validate-only",
            "--dry-run",
            "--preset",
            "ram_8g",
            "--npartitions",
            "64",
            "--num-workers",
            "2",
            "--max-rows-per-partition",
            "1500000",
            "--matrix",
            "tmp/memory_benchmark_matrix.yaml",
            "--compare-candidate-python",
            "C:/python313/python.exe",
            "--compare-candidate-workdir",
            "C:/work/candidate",
            "--compare-candidate-pipeline",
            "services/task_benchmarking/pipelines/examples/sample_pipeline.json",
            "--repeat",
            "2",
        ]
    )

    assert options.pipeline.endswith("sample_pipeline.json")
    assert options.pipeline_format == "internal"
    assert options.exec_mode == "metadata_only"
    assert options.report == "tmp/report.txt"
    assert options.report_json == "tmp/report.json"
    assert options.output_root == "tmp/task_benchmarking/runs"
    assert options.run_id == "run-1"
    assert options.validate_only is True
    assert options.dry_run is True
    assert options.preset == "ram_8g"
    assert options.npartitions == 64
    assert options.num_workers == 2
    assert options.max_rows_per_partition == 1500000
    assert options.matrix == "tmp/memory_benchmark_matrix.yaml"
    assert options.compare_candidate_python == "C:/python313/python.exe"
    assert options.compare_candidate_workdir == "C:/work/candidate"
    assert options.compare_candidate_pipeline.endswith("sample_pipeline.json")
    assert options.repeat == 2
