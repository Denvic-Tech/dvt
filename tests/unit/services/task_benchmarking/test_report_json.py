from types import SimpleNamespace

from services.task_benchmarking import metrics
from services.task_benchmarking.recorder import BenchmarkRecorder, NodeMemoryStats
from services.task_benchmarking.report_json import build_report_payload

from src.nodes.write.write_df_to_db_v4 import WriteDataFrameToDBV4
from src.nodes.write.write_df_to_db_v4.node import WriteDataFrameToDBV4SystemVariables


def _writer_outputs(rows_written: int) -> dict:
    writer = WriteDataFrameToDBV4(user_id="u", project_id="p", task_id="t", node_id="write")
    writer.emit_system_variables(
        WriteDataFrameToDBV4SystemVariables(target_table="bench", rows_written=rows_written)
    )
    return writer.get_outputs()


def _stats(node_id: str, node_name: str, duration: float) -> NodeMemoryStats:
    return NodeMemoryStats(
        node_id=node_id,
        node_name=node_name,
        start_time=100.0,
        start_rss=1,
        end_time=100.0 + duration,
        end_rss=2,
        peak_rss=3,
        status="success",
    )


def test_payload_reports_rows_rows_per_s_and_sink_total(benchmark_registry, schema_errors) -> None:
    task = SimpleNamespace(
        task_id="task-1",
        project_id="project-1",
        pipeline={
            "data": SimpleNamespace(name="BenchmarkSyntheticDataFrame"),
            "write": SimpleNamespace(name="WriteDataFrameToDBV4"),
            "materialize": SimpleNamespace(name="BenchmarkMaterialize"),
        },
    )
    processor = SimpleNamespace(
        executed_nodes=["data", "write", "materialize"],
        failed_nodes=[],
        skipped_nodes=[],
        nodes_outputs={"write": _writer_outputs(rows_written=1_000)},
    )
    recorder = BenchmarkRecorder(sample_interval_sec=0.1, collect_metadata=False)
    recorder.node_stats = {
        "data": _stats("data", "BenchmarkSyntheticDataFrame", duration=1.0),
        "write": _stats("write", "WriteDataFrameToDBV4", duration=2.0),
        "materialize": _stats("materialize", "BenchmarkMaterialize", duration=0.5),
    }
    metrics.reset()
    metrics.record_metric("data", "rows", 1_000)
    metrics.record_metric("materialize", "rows", 250)

    payload = build_report_payload(
        task=task,
        processor=processor,
        recorder=recorder,
        success=True,
        include_metadata=False,
    )

    nodes = {node["node_id"]: node for node in payload["nodes"]}
    assert nodes["write"]["metrics"] == {"rows": 1_000}
    assert nodes["write"]["rows_per_s"] == 500.0
    assert nodes["materialize"]["rows_per_s"] == 500.0
    assert nodes["data"]["rows_per_s"] == 1_000.0
    # Only sink (OUTPUT_NODE) rows are summed; the synthetic source is excluded.
    assert payload["rows_total"] == 1_250
    assert schema_errors(payload, "benchmark_report.schema.json", "taskReport") == []
