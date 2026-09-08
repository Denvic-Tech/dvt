import pandas as pd
from dask import dataframe as dd

from core.metadata import get_df_metadata
from core.utils import get_useful_indexes
from src.nodes.transform.df_rename_columns import DataFrameRenameColumns


def _build_dual_role_ddf() -> dd.DataFrame:
    pdf = pd.DataFrame({"k": range(20), "value": range(100, 120)})
    pdf.index = pd.Index(pdf["k"], name="k")
    return dd.from_pandas(pdf, npartitions=4, sort=True)


def test_rename_business_index_column_keeps_index_fast_path_metadata():
    source = _build_dual_role_ddf()

    node = DataFrameRenameColumns(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="rename-node",
        df=source,
        mapping={"k": "k2"},
    )
    node.process()
    result = node.output

    assert list(result.columns) == ["k2", "value"]
    assert result.index.name == "k2"
    assert result.known_divisions is True
    assert result.divisions == source.divisions
    assert get_useful_indexes(result) == ["k2"]

    metadata_by_name = {column.name: column for column in get_df_metadata(result).columns}
    assert "k" not in metadata_by_name
    assert metadata_by_name["k2"].index is True
