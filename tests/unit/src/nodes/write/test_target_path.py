import pytest

from src.nodes.write._target_path import normalize_relative_target_path
from src.nodes.write.save_excel import SaveExcel


def test_normalize_relative_target_path_appends_missing_extension() -> None:
    assert normalize_relative_target_path("reports/export", ".csv") == "reports/export.csv"


def test_normalize_relative_target_path_keeps_single_extension() -> None:
    assert normalize_relative_target_path("reports/export.xlsx", ".xlsx") == "reports/export.xlsx"


def test_normalize_relative_target_path_collapses_repeated_extensions() -> None:
    assert normalize_relative_target_path("reports/export.csv.csv", ".csv") == "reports/export.csv"


def test_normalize_relative_target_path_requires_file_name() -> None:
    with pytest.raises(ValueError, match="path cannot be empty"):
        normalize_relative_target_path("", ".parquet")


def test_save_excel_part_key_uses_full_path_stem() -> None:
    node = SaveExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="save-excel-node",
        connection=object(),
        df=object(),
        path="reports/export.xlsx",
    )

    assert node._part_key(node._target_key_single(), 1) == "reports/export-part-00001.xlsx"
