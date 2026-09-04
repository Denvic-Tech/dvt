import pandas as pd
from dask import dataframe as dd

from core.metadata import get_df_metadata
from core.utils import get_useful_indexes
from src.nodes.transform.df_drop_columns import DataFrameDropColumns


def _build_dual_role_ddf() -> dd.DataFrame:
    pdf = pd.DataFrame({"k": range(20), "value": range(100, 120)})
    pdf.index = pd.Index(pdf["k"], name="k")
    return dd.from_pandas(pdf, npartitions=4, sort=True)


def _build_drop_node(df: dd.DataFrame, columns: list[str]) -> DataFrameDropColumns:
    return DataFrameDropColumns(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="drop-node",
        df=df,
        columns=columns,
    )


def test_drop_business_index_column_internalizes_physical_index_without_losing_divisions():
    source = _build_dual_role_ddf()
    original_divisions = source.divisions

    node = _build_drop_node(source, ["k"])
    node.process()
    result = node.output

    assert list(result.columns) == ["value"]
    assert result.index.name == "__dvt_partition_key"
    assert result.known_divisions is True
    assert result.divisions == original_divisions
    assert get_useful_indexes(result) == []

    metadata = get_df_metadata(result)
    assert [column.name for column in metadata.columns] == ["value"]

    computed = result.compute()
    assert list(computed.columns) == ["value"]
    assert computed["value"].tolist() == list(range(100, 120))


def test_drop_non_index_column_keeps_business_index_semantics():
    source = _build_dual_role_ddf()

    node = _build_drop_node(source, ["value"])
    node.process()
    result = node.output

    assert list(result.columns) == ["k"]
    assert result.index.name == "k"
    assert get_useful_indexes(result) == ["k"]
    metadata_by_name = {column.name: column for column in get_df_metadata(result).columns}
    assert metadata_by_name["k"].index is True
