import pandas as pd

from core.metadata.df_metadata import get_df_metadata
from core.types import DataType


def test_get_df_metadata_includes_named_index():
    df = pd.DataFrame({"value": [1, 2, 3]})
    df.index.name = "idx"

    metadata = get_df_metadata(df)
    columns = {col.name: col for col in metadata.columns}

    assert "idx" in columns
    assert columns["idx"].index is True
    assert columns["value"].index is False


def test_get_df_metadata_skips_default_range_index():
    df = pd.DataFrame({"value": [1, 2, 3]})

    metadata = get_df_metadata(df)
    names = [col.name for col in metadata.columns]

    assert "value" in names
    assert all(col.name != "index" for col in metadata.columns)


def test_get_df_metadata_multiindex_levels():
    index = pd.MultiIndex.from_tuples(
        [("A", 1), ("B", 2)],
        names=["letter", "number"],
    )
    df = pd.DataFrame({"value": [10, 20]}, index=index)

    metadata = get_df_metadata(df)
    columns = {col.name: col for col in metadata.columns}

    assert "letter" in columns
    assert "number" in columns
    assert columns["letter"].index is True
    assert columns["number"].index is True


def test_get_df_metadata_types_are_mapped():
    df = pd.DataFrame({
        "int_col": pd.Series([1, 2], dtype="int64"),
        "float_col": pd.Series([1.0, 2.0], dtype="float64"),
        "str_col": pd.Series(["a", "b"], dtype="string"),
    })

    metadata = get_df_metadata(df)
    columns = {col.name: col for col in metadata.columns}

    assert columns["int_col"].dtype == DataType.INT
    assert columns["float_col"].dtype == DataType.FLOAT
    assert columns["str_col"].dtype == DataType.STRING


def test_get_df_metadata_populates_dtype_metadata():
    df = pd.DataFrame({
        "int_col": pd.Series([1, 2], dtype="int64"),
        "nullable_int_col": pd.Series([1, None], dtype="Int64"),
        "string_col": pd.Series(["a", "b"], dtype="string"),
        "datetime_tz_col": pd.Series(pd.date_range("2024-01-01", periods=2, tz="UTC")),
    })

    metadata = get_df_metadata(df)
    columns = {col.name: col for col in metadata.columns}

    int_meta = columns["int_col"].dtype_metadata
    assert int_meta is not None
    assert int_meta.name == "int64"
    assert int_meta.class_name.startswith("Int64")
    assert int_meta.origin == "numpy"
    assert int_meta.repr == "int64"
    assert int_meta.module == "numpy.dtypes"
    assert int_meta.kind == "i"
    assert int_meta.itemsize == 8
    assert int_meta.is_extension is False
    assert int_meta.scalar_type == "int64"

    nullable_int_meta = columns["nullable_int_col"].dtype_metadata
    assert nullable_int_meta is not None
    assert nullable_int_meta.name == "Int64"
    assert nullable_int_meta.origin == "pandas"
    assert nullable_int_meta.is_extension is True

    string_meta = columns["string_col"].dtype_metadata
    assert string_meta is not None
    assert string_meta.origin == "pandas"
    assert string_meta.storage in {"python", "pyarrow"}
    assert string_meta.scalar_type == "str"

    datetime_meta = columns["datetime_tz_col"].dtype_metadata
    assert datetime_meta is not None
    assert datetime_meta.origin == "pandas"
    assert datetime_meta.kind == "M"
    assert datetime_meta.timezone == "UTC"
    assert datetime_meta.unit is not None


def test_get_df_metadata_populates_categorical_dtype_metadata():
    category_dtype = pd.CategoricalDtype(categories=["low", "mid", "high"], ordered=True)
    df = pd.DataFrame({
        "category_col": pd.Series(["low", "high"], dtype=category_dtype),
    })

    metadata = get_df_metadata(df)
    columns = {col.name: col for col in metadata.columns}

    category_meta = columns["category_col"].dtype_metadata
    assert category_meta is not None
    assert category_meta.origin == "pandas"
    assert category_meta.ordered is True
    assert category_meta.categories_count == 3
    assert category_meta.categories_dtype is not None


def test_get_df_metadata_merges_named_index_with_same_column_name():
    df = pd.DataFrame({"id": pd.Series([1, 2], dtype="Int64"), "value": [10, 20]})
    df.index = pd.Index(df["id"], dtype="Int64", name="id")

    metadata = get_df_metadata(df)
    id_columns = [column for column in metadata.columns if column.name == "id"]

    assert len(id_columns) == 1
    assert id_columns[0].index is True
    assert id_columns[0].dtype == DataType.INT
    assert id_columns[0].dtype_metadata is not None
    assert id_columns[0].dtype_metadata.name == "Int64"
    assert id_columns[0].dtype_metadata.is_extension is True


def test_get_df_metadata_skips_internal_dvt_index():
    df = pd.DataFrame({"value": [10, 20]})
    df.index = pd.Index([0, 1], dtype="int64", name="__dvt_partition_bucket")

    metadata = get_df_metadata(df)
    names = [col.name for col in metadata.columns]

    assert "value" in names
    assert "__dvt_partition_bucket" not in names


def test_get_df_metadata_skips_internal_dvt_columns():
    df = pd.DataFrame(
        {
            "value": [10, 20],
            "__dvt_partition_bucket": [0, 1],
            "__dvt_partition_bucket_left": [0, 1],
            "__dvt_partition_bucket_right": [0, 1],
        }
    )

    metadata = get_df_metadata(df)
    names = [col.name for col in metadata.columns]

    assert "value" in names
    assert "__dvt_partition_bucket" not in names
    assert "__dvt_partition_bucket_left" not in names
    assert "__dvt_partition_bucket_right" not in names
