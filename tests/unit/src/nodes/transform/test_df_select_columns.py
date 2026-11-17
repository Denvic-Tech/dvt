import pandas as pd
from dask import dataframe as dd

from core.utils import get_useful_indexes

from src.nodes.transform.df_select_columns import DataFrameSelectColumns


def test_select_retains_requested_column_with_the_same_name_as_index():
    pdf = pd.DataFrame({"k": range(20), "value": range(100, 120)})
    pdf.index = pd.Index(pdf["k"], name="k")
    source = dd.from_pandas(pdf, npartitions=4, sort=True)

    node = DataFrameSelectColumns(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="select-node",
        df=source,
        columns=["k", "value"],
    )
    node.process()

    assert list(node.output.columns) == ["k", "value"]
    assert node.output.compute()["k"].tolist() == list(range(20))
    assert node.output.index.name == "k"
    assert node.output.known_divisions is True
    assert get_useful_indexes(node.output) == ["k"]


def test_select_keeps_index_only_field_on_the_index():
    pdf = pd.DataFrame({"k": [1, 2], "value": [3, 4]}).set_index("k")
    node = DataFrameSelectColumns(
        user_id="user", project_id="project", task_id="task", node_id="select-node",
        df=dd.from_pandas(pdf, npartitions=2), columns=["k", "value"],
    )
    node.process()
    pd.testing.assert_frame_equal(node.output.compute(), pdf)
