import pandas as pd
from dask import dataframe as dd

from src.nodes.transform import DataFrameJoin, DataFrameRenameColumns


class _FakeExpr:
    def __init__(self, mapping_columns):
        self.unique_partition_mapping_columns_from_shuffle = mapping_columns


class _FakeDataFrame:
    def __init__(self, mapping_columns):
        self.expr = _FakeExpr(mapping_columns)
        self._meta = object()
        self.map_partitions_called = False
        self.last_meta = None

    def map_partitions(self, func, meta):
        self.map_partitions_called = True
        self.last_meta = meta
        return "cleared-dataframe"


def _build_join_node(*, left: dd.DataFrame, right: dd.DataFrame) -> DataFrameJoin:
    return DataFrameJoin(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-join",
        left=left,
        right=right,
        left_on=["ArticleCode"],
        right_on=["ArticleCode"],
        how="left",
    )


def test_df_join_does_not_leak_internal_index_name_as_column():
    left_pdf = pd.DataFrame(
        {
            "ArticleCode": ["A", "B"],
            "left_value": [1, 2],
        }
    )
    left_pdf.index = pd.Index([0, 1], dtype="int64", name="__dvt_partition_bucket")

    right_pdf = pd.DataFrame(
        {
            "ArticleCode": ["A", "B"],
            "right_value": [10, 20],
        }
    )

    node = _build_join_node(
        left=dd.from_pandas(left_pdf, npartitions=1),
        right=dd.from_pandas(right_pdf, npartitions=1),
    )
    node.process()

    result = node.output.compute()

    assert list(result.columns) == ["ArticleCode", "left_value", "right_value"]
    assert all(not str(column).startswith("__dvt_") for column in result.columns)


def test_df_join_drops_internal_dvt_columns_after_merge():
    left_pdf = pd.DataFrame(
        {
            "ArticleCode": ["A", "B"],
            "left_value": [1, 2],
            "__dvt_partition_bucket_left": [0, 1],
        }
    )

    right_pdf = pd.DataFrame(
        {
            "ArticleCode": ["A", "B"],
            "right_value": [10, 20],
            "__dvt_partition_bucket": [0, 1],
            "__dvt_partition_bucket_right": [0, 1],
        }
    )

    node = _build_join_node(
        left=dd.from_pandas(left_pdf, npartitions=1),
        right=dd.from_pandas(right_pdf, npartitions=1),
    )
    node.process()

    result = node.output.compute()

    assert "ArticleCode" in result.columns
    assert "left_value" in result.columns
    assert "right_value" in result.columns
    assert all(not str(column).startswith("__dvt_") for column in result.columns)


def test_df_join_rename_only_right_columns():
    left_pdf = pd.DataFrame(
        {
            "ArticleCode": ["A", "B"],
            "left_value": [1, 2],
            "conflict_column_1": [3, 4],
            "conflict_column_2": [5, 6],
            "__dvt_partition_bucket_left": [0, 1],
        }
    )

    right_pdf = pd.DataFrame(
        {
            "ArticleCode": ["A", "B"],
            "right_value": [10, 20],
            "conflict_column_1": [7, 8],
            "conflict_column_2": [9, 10],
            "__dvt_partition_bucket": [0, 1],
            "__dvt_partition_bucket_right": [0, 1],
        }
    )

    node = _build_join_node(
        left=dd.from_pandas(left_pdf, npartitions=1),
        right=dd.from_pandas(right_pdf, npartitions=1),
    )
    node.process()

    result = node.output.compute()

    expected_columns = {
        "ArticleCode",
        "left_value",
        "right_value",
        "conflict_column_1",
        "conflict_column_2",
        "conflict_column_1_right",
        "conflict_column_2_right"
    }

    assert set(result.columns) == expected_columns

    assert all(not str(column).startswith("__dvt_") for column in result.columns)


def test_df_join_accepts_string_join_keys():
    left_pdf = pd.DataFrame(
        {
            "ArticleCode": ["A", "B"],
            "left_value": [1, 2],
        }
    )
    right_pdf = pd.DataFrame(
        {
            "ArticleCode": ["A", "B"],
            "right_value": [10, 20],
        }
    )

    node = DataFrameJoin(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-join",
        left=dd.from_pandas(left_pdf, npartitions=1),
        right=dd.from_pandas(right_pdf, npartitions=1),
        left_on="ArticleCode",
        right_on="ArticleCode",
        how="left",
    )
    node.process()

    result = node.output.compute().reset_index(drop=True)

    expected = pd.DataFrame(
        {
            "ArticleCode": ["A", "B"],
            "left_value": [1, 2],
            "right_value": [10, 20],
        }
    )
    pd.testing.assert_frame_equal(result, expected, check_dtype=False)


def test_df_join_handles_drop_duplicates_before_right_column_rename():
    left_pdf = pd.DataFrame(
        {
            "PartnerHolding": ["A", "B"],
            "region": ["left-1", "left-2"],
        }
    )
    right_pdf = pd.DataFrame(
        {
            "TITLE": ["A", "B", "B"],
            "region": ["right-1", "right-2", "right-2"],
        }
    )

    node = DataFrameJoin(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-join",
        left=dd.from_pandas(left_pdf, npartitions=1),
        right=dd.from_pandas(right_pdf, npartitions=2).drop_duplicates(),
        left_on=["PartnerHolding"],
        right_on=["TITLE"],
        how="left",
    )
    node.process()

    result = node.output.compute().reset_index(drop=True)

    expected = pd.DataFrame(
        {
            "PartnerHolding": ["A", "B"],
            "region": ["left-1", "left-2"],
            "TITLE": ["A", "B"],
            "region_right": ["right-1", "right-2"],
        }
    )
    pd.testing.assert_frame_equal(result, expected, check_dtype=False)


def test_df_join_clears_invalid_tuple_partition_mapping_before_rename():
    fake_right = _FakeDataFrame({(None, "TITLE")})

    result = DataFrameJoin._clear_invalid_partition_mapping_before_rename(fake_right)

    assert result == "cleared-dataframe"
    assert fake_right.map_partitions_called is True
    assert fake_right.last_meta is fake_right._meta


def _expr_contains_shuffle(expr) -> bool:
    seen: set[int] = set()
    stack = [expr]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if "shuffle" in type(current).__name__.lower():
            return True
        stack.extend(
            operand
            for operand in (getattr(current, "operands", ()) or ())
            if hasattr(operand, "operands")
        )
    return False


def _build_indexed_join_frame(value_column: str) -> dd.DataFrame:
    pdf = pd.DataFrame({"k": range(100), value_column: range(100)})
    pdf.index = pd.Index(pdf["k"], name="k")
    return dd.from_pandas(pdf, npartitions=5, sort=True)


def test_df_join_business_index_fast_path_keeps_known_divisions_without_shuffle():
    left = _build_indexed_join_frame("left_value")
    right = _build_indexed_join_frame("right_value")

    node = DataFrameJoin(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-join-indexed",
        left=left,
        right=right,
        left_on=["k"],
        right_on=["k"],
        how="inner",
    )
    node.process()

    assert node.output.known_divisions is True
    assert _expr_contains_shuffle(node.output.expr) is False
    assert len(node.output.compute()) == 100


def test_df_join_renamed_business_index_fast_path_keeps_no_shuffle():
    left = _build_indexed_join_frame("left_value")
    right = _build_indexed_join_frame("right_value")

    renamed_frames = []
    for node_id, frame in (("rename-left", left), ("rename-right", right)):
        rename_node = DataFrameRenameColumns(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id=node_id,
            df=frame,
            mapping={"k": "k2"},
        )
        rename_node.process()
        renamed_frames.append(rename_node.output)

    node = DataFrameJoin(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-join-renamed-indexed",
        left=renamed_frames[0],
        right=renamed_frames[1],
        left_on=["k2"],
        right_on=["k2"],
        how="inner",
    )
    node.process()

    assert node.output.known_divisions is True
    assert _expr_contains_shuffle(node.output.expr) is False
    assert len(node.output.compute()) == 100
