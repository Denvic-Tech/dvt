import dask.dataframe as dd
import pandas as pd

from src.nodes.transform.df_pivot import DataFramePivot


def _node(pdf: pd.DataFrame, aggfunc: dict[str, str]) -> DataFramePivot:
    return DataFramePivot(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-df-pivot",
        df=dd.from_pandas(pdf, npartitions=2),
        index="Object",
        column="Field_name",
        aggfunc=aggfunc,
    )


def test_pivot_uses_field_values_as_column_names_without_prefix() -> None:
    node = _node(
        pd.DataFrame(
            {
                "Object": ["A", "A", "B", "B"],
                "Field_name": ["Height", "Width", "Height", "Width"],
                "Field_value": [10, 20, 15, 25],
            }
        ),
        {"Field_value": "first"},
    )

    node.process()
    result = node.output.compute().sort_index()

    assert list(result.columns) == ["Height", "Width"]
    assert result.loc["A"].tolist() == [10, 20]
    assert result.loc["B"].tolist() == [15, 25]


def test_pivot_prefixes_only_later_duplicate_value_columns() -> None:
    node = _node(
        pd.DataFrame(
            {
                "Object": ["A", "A", "B", "B"],
                "Field_name": ["Height", "Width", "Height", "Width"],
                "Field_value": [10, 20, 15, 25],
                "Field_count": [1, 2, 3, 4],
            }
        ),
        {"Field_value": "first", "Field_count": "count"},
    )

    node.process()
    result = node.output.compute().sort_index()

    assert set(result.columns) == {
        "Height",
        "Width",
        "Field_count_Height",
        "Field_count_Width",
    }
    assert result.loc["A", "Height"] == 10
    assert result.loc["A", "Field_count_Height"] == 1


def test_flatten_prefixes_only_names_that_are_actually_duplicated() -> None:
    node = _node(
        pd.DataFrame(
            {
                "Object": ["A"],
                "Field_name": ["Height"],
                "Metric_A": [1],
                "Metric_B": [2],
            }
        ),
        {"Metric_A": "first", "Metric_B": "first"},
    )
    columns = pd.MultiIndex.from_tuples(
        [
            ("Metric_A", "Height"),
            ("Metric_A", "Width"),
            ("Metric_B", "Width"),
            ("Metric_B", "Depth"),
        ]
    )

    result = node._build_flat_column_names(columns)

    assert result == ["Height", "Width", "Metric_B_Width", "Depth"]


def test_pivot_adds_numeric_suffix_when_prefix_matches_field_name() -> None:
    node = _node(
        pd.DataFrame(
            {
                "Object": ["A", "A"],
                "Field_name": ["Height", "Field_count_Height"],
                "Field_value": [10, 20],
                "Field_count": [1, 2],
            }
        ),
        {"Field_value": "first", "Field_count": "count"},
    )

    node.process()
    result = node.output.compute()

    assert set(result.columns) == {
        "Height",
        "Field_count_Height",
        "Field_count_Height_2",
        "Field_count_Field_count_Height",
    }
    assert result.loc["A", "Field_count_Height"] == 20
    assert result.loc["A", "Field_count_Height_2"] == 1
