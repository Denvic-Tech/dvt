from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class BenchmarkOptions:
    pipeline: str
    pipeline_format: str
    exec_mode: str
    report: Optional[str]
    report_json: Optional[str]
    output_root: str
    run_id: Optional[str]
    outputs: list[str]
    user_id: Optional[str]
    sample_interval: float
    repeat: int
    repeat_include_reports: bool
    patches: list[str]
    include_metadata: bool
    validate_only: bool
    dry_run: bool
    preset: Optional[str]
    npartitions: Optional[int]
    num_workers: Optional[int]
    max_rows_per_partition: Optional[int]
    matrix: Optional[str]
    compare_candidate_python: Optional[str]
    compare_candidate_workdir: Optional[str]
    compare_candidate_pipeline: Optional[str]
    run_once: bool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a pipeline and report memory usage.")
    parser.add_argument("--pipeline", required=True, help="Path to a pipeline JSON file")
    parser.add_argument(
        "--pipeline-format",
        choices=["auto", "internal", "ui_graph"],
        default="auto",
        help="Explicit pipeline JSON format",
    )
    parser.add_argument(
        "--exec-mode",
        choices=["full", "metadata_only"],
        default="full",
        help="Execute the full pipeline or only node metadata lifecycle.",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Optional path to write the report text",
    )
    parser.add_argument(
        "--report-json",
        default=None,
        help="Optional path to write the report JSON",
    )
    parser.add_argument(
        "--output-root",
        default="tmp/task_benchmarking/runs",
        help="Root directory for structured run artifacts",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional explicit run id for output directory naming",
    )
    parser.add_argument(
        "--outputs",
        nargs="*",
        default=[],
        help="Optional list of node IDs to execute",
    )
    parser.add_argument(
        "--user-id",
        default=None,
        help="Override task user_id (or set TASK_BENCHMARKING_USER_ID).",
    )
    parser.add_argument(
        "--sample-interval",
        type=float,
        default=0.1,
        help="Sampling interval in seconds for RSS measurements",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Repeat the pipeline multiple times in one process to detect leaks",
    )
    parser.add_argument(
        "--repeat-include-reports",
        action="store_true",
        help="Include full per-run reports in the output when using --repeat",
    )
    parser.add_argument(
        "--include-metadata",
        action="store_true",
        help="Include per-node output metadata in human/LLM-friendly formats",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate input pipeline and options without executing nodes",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve options and artifacts without executing pipeline",
    )
    parser.add_argument(
        "--preset",
        choices=["ram_8g", "ram_16g"],
        default=None,
        help="Resource preset for constrained-memory runs",
    )
    parser.add_argument(
        "--npartitions",
        type=int,
        default=None,
        help="Override node input npartitions globally",
    )
    parser.add_argument(
        "--num-workers",
        type=int,
        default=None,
        help="Override node input num_workers globally",
    )
    parser.add_argument(
        "--max-rows-per-partition",
        type=int,
        default=None,
        help="Override node input max_rows_per_partition globally",
    )
    parser.add_argument(
        "--matrix",
        default=None,
        help="Path to matrix config (JSON/YAML) for scenario runs",
    )
    parser.add_argument(
        "--compare-candidate-python",
        default=None,
        help="Python executable for safe candidate comparison run",
    )
    parser.add_argument(
        "--compare-candidate-workdir",
        default=None,
        help="Working directory for candidate comparison run",
    )
    parser.add_argument(
        "--compare-candidate-pipeline",
        default=None,
        help="Candidate pipeline path for safe comparison (default: --pipeline)",
    )
    parser.add_argument(
        "--patch",
        dest="patches",
        action="append",
        default=[],
        help="Path to a git patch file (repeatable).",
    )
    parser.add_argument(
        "--_once",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def parse_args(argv: Optional[list[str]] = None) -> BenchmarkOptions:
    parser = build_parser()
    args = parser.parse_args(argv)
    return BenchmarkOptions(
        pipeline=args.pipeline,
        pipeline_format=args.pipeline_format,
        exec_mode=args.exec_mode,
        report=args.report,
        report_json=args.report_json,
        output_root=args.output_root,
        run_id=args.run_id,
        outputs=args.outputs,
        user_id=args.user_id,
        sample_interval=args.sample_interval,
        repeat=args.repeat,
        repeat_include_reports=args.repeat_include_reports,
        patches=args.patches,
        include_metadata=args.include_metadata,
        validate_only=args.validate_only,
        dry_run=args.dry_run,
        preset=args.preset,
        npartitions=args.npartitions,
        num_workers=args.num_workers,
        max_rows_per_partition=args.max_rows_per_partition,
        matrix=args.matrix,
        compare_candidate_python=args.compare_candidate_python,
        compare_candidate_workdir=args.compare_candidate_workdir,
        compare_candidate_pipeline=args.compare_candidate_pipeline,
        run_once=args._once,
    )
