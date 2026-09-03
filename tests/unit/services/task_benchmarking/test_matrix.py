from pathlib import Path

from services.task_benchmarking.matrix import load_matrix_cases


def test_load_matrix_cases_from_json_config(tmp_path: Path) -> None:
    matrix_path = tmp_path / "matrix.json"
    matrix_path.write_text(
        """
{
  "pipelines": [
    {"path": "testing_services/task_benchmarking/pipelines/examples/sample_pipeline.json", "name": "sample"}
  ],
  "parameters": {
    "npartitions": [16, 32],
    "num_workers": [1, 2]
  }
}
""".strip(),
        encoding="utf-8",
    )

    cases = load_matrix_cases(
        matrix_path=str(matrix_path),
        default_pipeline="testing_services/task_benchmarking/pipelines/examples/sample_pipeline.json",
        default_pipeline_format="auto",
    )

    assert len(cases) == 4
    assert all(case.pipeline.path.endswith("sample_pipeline.json") for case in cases)
    assert all("npartitions" in case.overrides for case in cases)


def test_load_matrix_cases_supports_explicit_cases(tmp_path: Path) -> None:
    matrix_path = tmp_path / "matrix.json"
    matrix_path.write_text(
        """
{
  "cases": [
    {
      "name": "custom",
      "pipeline": "testing_services/task_benchmarking/pipelines/examples/sample_pipeline.json",
      "pipeline_format": "internal",
      "overrides": {"npartitions": 64},
      "node_overrides": {
        "read": {"num_workers": 2}
      }
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    cases = load_matrix_cases(
        matrix_path=str(matrix_path),
        default_pipeline="testing_services/task_benchmarking/pipelines/examples/sample_pipeline.json",
        default_pipeline_format="auto",
    )

    assert len(cases) == 1
    case = cases[0]
    assert case.name == "custom"
    assert case.pipeline.pipeline_format == "internal"
    assert case.overrides["npartitions"] == 64
    assert case.node_overrides["read"]["num_workers"] == 2
