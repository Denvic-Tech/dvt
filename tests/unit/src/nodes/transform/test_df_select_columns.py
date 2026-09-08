import pandas as pd
from dask import dataframe as dd

from core.utils import get_useful_indexes
from src.nodes.transform.df_select_columns import DataFrameSelectColumns


def test_select_business_index_keeps_legacy_index_projection_semantics():
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

    assert list(node.output.columns) == ["value"]
    assert node.output.index.name == "k"
    assert node.output.known_divisions is True
    assert get_useful_indexes(node.output) == ["k"]
