import pandas as pd
import pytest
from dask import dataframe as dd

from core.types.dataframe_index import PhysicalDataFrameIndex
from core.utils.dataframe_index import set_physical_index

from src.nodes.transform.df_join import DataFrameJoin
from src.nodes.transform.df_rename_columns import DataFrameRenameColumns


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


def _build_indexed_join_frame(value_column: str, keys=(1, 2, 2, 3)) -> dd.DataFrame:
    pdf = pd.DataFrame({value_column: range(len(keys)), "k": keys})
    name = "__dvt_partition_key"
    pdf = pdf.set_index("k", drop=False).rename_axis(name)
    return set_physical_index(
        dd.from_pandas(pdf, npartitions=2),
        PhysicalDataFrameIndex(name=name, strategy="range", source_column="k", bound_column="k"),
    )


@pytest.mark.parametrize("how", ["inner", "left", "right", "outer"])
def test_df_join_bound_index_keeps_column_merge_schema_without_shuffle(how):
    left = _build_indexed_join_frame("left_value")
    right = _build_indexed_join_frame("right_value", keys=(2, 2, 3, 4))

    node = DataFrameJoin(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-join-indexed",
        left=left,
        right=right,
        left_on=["k"],
        right_on=["k"],
        how=how,
    )
    node.process()

    assert node.output.known_divisions is True
    assert _expr_contains_shuffle(node.output.optimize(fuse=False).expr) is False
    expected = left.compute().merge(right.compute(), on="k", how=how)
    actual = node.output.compute()
    order = ["k", "left_value", "right_value"]
    pd.testing.assert_frame_equal(
        actual.sort_values(order).reset_index(drop=True),
        expected.sort_values(order).reset_index(drop=True),
    )


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
    assert len(node.output.compute()) == 6


@pytest.mark.parametrize(
    ("left_keys", "right_keys", "how", "expected"),
    [
        (["YearKey"], ["year"], "inner", [11, 12]),
        (["email"], ["email"], "left", [11, 12]),
        (["YearKey", "email"], ["year", "email"], "inner", [11, 12]),
        (None, None, "cross", [11, 11, 12, 12]),
    ],
)
def test_df_join_handles_legacy_column_and_index_name_collision(
    left_keys, right_keys, how, expected
):
    left = pd.DataFrame(
        {"YearKey": [11, 12], "email": ["a", "b"]},
        index=pd.Index([1, 2], name="YearKey"),
    )
    right = pd.DataFrame({"year": [11, 12], "email": ["a", "b"]})
    node = DataFrameJoin(
        user_id="user", project_id="project", task_id="task", node_id="legacy-join",
        left=dd.from_pandas(left, npartitions=2),
        right=dd.from_pandas(right, npartitions=2),
        left_on=left_keys, right_on=right_keys, how=how,
    )
    node.process()
    assert sorted(node.output.compute()["YearKey"]) == expected


def test_df_join_can_use_a_key_present_only_in_the_business_index():
    left = pd.DataFrame({"k": [1, 2], "label": ["a", "b"]}).set_index("k")
    right = pd.DataFrame({"code": [2, 3], "value": [20, 30]})
    node = DataFrameJoin(
        user_id="user", project_id="project", task_id="task", node_id="index-only-join",
        left=dd.from_pandas(left, npartitions=2),
        right=dd.from_pandas(right, npartitions=2),
        left_on=["k"], right_on=["code"], how="inner",
    )
    node.process()
    assert node.output.compute()[["label", "value"]].to_dict("records") == [
        {"label": "b", "value": 20}
    ]


def test_df_join_with_omitted_keys_does_not_join_by_physical_index():
    left = _build_indexed_join_frame("left_value", keys=(1, 2))
    right = _build_indexed_join_frame("right_value", keys=(2, 3))
    right = right.assign(k=right.k + 10)
    node = DataFrameJoin(
        user_id="user", project_id="project", task_id="task", node_id="implicit-key-join",
        left=left, right=right, how="inner",
    )
    node.process()
    assert node.output.compute().empty
