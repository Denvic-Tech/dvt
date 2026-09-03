from pathlib import Path

from services.task_benchmarking.utils import (
    apply_input_overrides,
    cartesian_parameter_grid,
    prepare_run_paths,
    resolve_pipeline_path,
)


def test_resolve_pipeline_path_supports_legacy_location() -> None:
    legacy_path = "services/task_benchmarking/sample_pipeline.json"
    resolved = Path(resolve_pipeline_path(legacy_path)).resolve()

    assert resolved.name == "sample_pipeline.json"
    assert "services" in resolved.parts
    assert "pipelines" in resolved.parts


def test_prepare_run_paths_creates_default_artifact_paths(tmp_path: Path) -> None:
    paths = prepare_run_paths(
        pipeline_path="services/task_benchmarking/pipelines/examples/sample_pipeline.json",
        output_root=str(tmp_path),
        run_id="manual-run-id",
        report_text_path=None,
        report_json_path=None,
    )

    assert Path(paths.run_dir).exists()
    assert paths.report_text_path.endswith("report.txt")
    assert paths.report_json_path.endswith("report.json")
    assert paths.config_path.endswith("config.json")
    assert paths.env_path.endswith("env.txt")


def test_prepare_run_paths_sanitizes_run_id(tmp_path: Path) -> None:
    paths = prepare_run_paths(
        pipeline_path="services/task_benchmarking/pipelines/examples/sample_pipeline.json",
        output_root=str(tmp_path),
        run_id="../unsafe run id",
        report_text_path=None,
        report_json_path=None,
    )

    assert Path(paths.run_dir).name == "unsafe-run-id"


def test_apply_input_overrides_updates_constant_inputs() -> None:
    pipeline = {
        "read": {
            "name": "ReadNode",
            "inputs": {
                "npartitions": {"__dvt_type": "const", "value": 16},
                "num_workers": {"__dvt_type": "const", "value": 1},
            },
        }
    }

    patched = apply_input_overrides(
        pipeline,
        global_overrides={"npartitions": 64},
        node_overrides={"read": {"num_workers": 2}},
    )

    assert pipeline["read"]["inputs"]["npartitions"]["value"] == 16
    assert patched["read"]["inputs"]["npartitions"]["value"] == 64
    assert patched["read"]["inputs"]["num_workers"]["value"] == 2


def test_cartesian_parameter_grid_builds_cross_product() -> None:
    grid = cartesian_parameter_grid({"npartitions": [16, 32], "num_workers": [1, 2]})

    assert len(grid) == 4
    assert {tuple(sorted(item.items())) for item in grid} == {
        (("npartitions", 16), ("num_workers", 1)),
        (("npartitions", 16), ("num_workers", 2)),
        (("npartitions", 32), ("num_workers", 1)),
        (("npartitions", 32), ("num_workers", 2)),
    }
