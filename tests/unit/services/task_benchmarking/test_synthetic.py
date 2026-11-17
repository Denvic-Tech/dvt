import numpy as np
import pandas as pd
import pytest

from services.task_benchmarking import synthetic


def _concat_plan(schema: str, rows: int, npartitions: int, seed: int = 42) -> pd.DataFrame:
    frames = [
        synthetic.generate_partition(schema, spec, seed)
        for spec in synthetic.partition_plan(rows, npartitions)
    ]
    return pd.concat(frames, ignore_index=True)


def test_partition_plan_is_contiguous_with_remainder_in_last_partition() -> None:
    plan = synthetic.partition_plan(10, 3)

    assert plan == [
        synthetic.PartitionSpec(index=0, id_offset=0, rows=3),
        synthetic.PartitionSpec(index=1, id_offset=3, rows=3),
        synthetic.PartitionSpec(index=2, id_offset=6, rows=4),
    ]


def test_partition_plan_clamps_npartitions_to_rows() -> None:
    plan = synthetic.partition_plan(3, 64)

    assert [spec.rows for spec in plan] == [1, 1, 1]
    assert [spec.id_offset for spec in plan] == [0, 1, 2]


@pytest.mark.parametrize(("rows", "npartitions"), [(-1, 1), (10, 0)])
def test_partition_plan_rejects_invalid_arguments(rows: int, npartitions: int) -> None:
    with pytest.raises(ValueError):
        synthetic.partition_plan(rows, npartitions)


@pytest.mark.parametrize("schema", synthetic.SCHEMA_NAMES)
def test_generate_partition_is_deterministic_and_order_independent(schema: str) -> None:
    plan = synthetic.partition_plan(3_000, 3)
    forward = [synthetic.generate_partition(schema, spec, 7) for spec in plan]
    backward = [synthetic.generate_partition(schema, spec, 7) for spec in reversed(plan)]

    for left, right in zip(forward, reversed(backward), strict=True):
        pd.testing.assert_frame_equal(left, right)
    other_seed = synthetic.generate_partition(schema, plan[0], 8)
    assert not forward[0].drop(columns="id").equals(other_seed.drop(columns="id"))


@pytest.mark.parametrize("schema", synthetic.SCHEMA_NAMES)
def test_ids_are_continuous_across_partitions(schema: str) -> None:
    frame = _concat_plan(schema, 1_001, 4)

    np.testing.assert_array_equal(frame["id"].to_numpy(), np.arange(1_001, dtype=np.int64))


@pytest.mark.parametrize("schema", synthetic.SCHEMA_NAMES)
def test_partition_dtypes_and_index_match_meta(schema: str) -> None:
    meta = synthetic.partition_meta(schema)
    frame = synthetic.generate_partition(schema, synthetic.PartitionSpec(5, 500, 100), 42)

    assert len(meta) == 0
    assert list(frame.columns) == synthetic.column_names(schema)
    pd.testing.assert_series_equal(frame.dtypes, meta.dtypes)
    assert isinstance(frame.index, pd.RangeIndex)
    assert isinstance(meta.index, pd.RangeIndex)
    assert frame["id"].tolist() == list(range(500, 600))


def test_wide_mixed_null_ratios_and_value_domains() -> None:
    frame = _concat_plan("wide_mixed", 200_000, 4)

    assert frame["int_b"].isna().mean() == pytest.approx(0.05, abs=0.005)
    assert frame["str_null"].isna().mean() == pytest.approx(0.10, abs=0.005)
    nullable = {"int_b", "str_null"}
    assert not frame.drop(columns=list(nullable)).isna().to_numpy().any()

    assert set(frame["str_low"].unique()) == {f"group_{i:02d}" for i in range(20)}
    assert set(frame["str_high"].str.len().unique()) == {16}
    assert set(frame["str_text"].str.len().unique()) == {64}
    assert frame["str_text"].str.fullmatch(r"[A-Za-z0-9_-]+").all()
    np.testing.assert_allclose(frame["amount"], frame["amount"].round(2))
    assert frame["ts_a"].min() >= pd.Timestamp("2020-01-01")
    assert frame["ts_a"].max() < pd.Timestamp("2026-01-01")
    assert (frame["ts_a"] == frame["ts_a"].dt.floor("ms")).all()
    assert (frame["date_a"] == frame["date_a"].dt.floor("D")).all()
    assert frame["bool_a"].mean() == pytest.approx(0.5, abs=0.01)


@pytest.mark.parametrize("schema", synthetic.SCHEMA_NAMES)
@pytest.mark.parametrize("dialect", synthetic.DIALECTS)
def test_create_table_sql_contains_every_column_and_primary_key(schema: str, dialect: str) -> None:
    statements = synthetic.create_table_sql(schema, dialect, "bench_t")
    ddl = statements[-1]

    assert len(statements) == 1
    assert ddl.startswith(f"CREATE TABLE {synthetic.quote_identifier(dialect, 'bench_t')} (")
    for column in synthetic.columns(schema):
        quoted = synthetic.quote_identifier(dialect, column.name)
        assert f"{quoted} {column.sql_type(dialect)}" in ddl
    if dialect == "clickhouse":
        assert ddl.endswith("ENGINE = MergeTree ORDER BY `id`")
    else:
        assert f"PRIMARY KEY ({synthetic.quote_identifier(dialect, 'id')})" in ddl


def test_nullability_follows_column_spec() -> None:
    postgres = synthetic.create_table_sql("wide_mixed", "postgres", "t")[0]
    clickhouse = synthetic.create_table_sql("wide_mixed", "clickhouse", "t")[0]

    assert '"int_b" BIGINT NULL' in postgres
    assert '"int_a" INTEGER NOT NULL' in postgres
    assert "`str_null` Nullable(String)" in clickhouse
    assert "`str_high` String," in clickhouse


@pytest.mark.parametrize(
    ("dialect", "expected"),
    [
        ("postgres", 'DROP TABLE IF EXISTS "s"."t"'),
        ("clickhouse", "DROP TABLE IF EXISTS `s`.`t`"),
        ("mssql", "DROP TABLE IF EXISTS [s].[t]"),
        ("mysql", "DROP TABLE IF EXISTS `s`.`t`"),
    ],
)
def test_drop_table_sql_qualifies_schema(dialect: str, expected: str) -> None:
    assert synthetic.drop_table_sql(dialect, "t", "s") == expected


def test_create_table_sql_creates_missing_schema_for_postgres_and_mssql() -> None:
    postgres = synthetic.create_table_sql("numeric", "postgres", "t", "bench")
    mssql = synthetic.create_table_sql("numeric", "mssql", "t", "bench")

    assert postgres[0] == 'CREATE SCHEMA IF NOT EXISTS "bench"'
    assert mssql[0].startswith("IF SCHEMA_ID(N'bench') IS NULL")
    assert len(synthetic.create_table_sql("numeric", "clickhouse", "t", "bench")) == 1


@pytest.mark.parametrize("name", ["bad;name", "t]", "1abc", ""])
def test_unsafe_identifiers_are_rejected(name: str) -> None:
    with pytest.raises(ValueError):
        synthetic.drop_table_sql("mssql", name)


def test_unknown_schema_and_dialect_are_rejected() -> None:
    with pytest.raises(ValueError):
        synthetic.partition_meta("missing")
    with pytest.raises(ValueError):
        synthetic.create_table_sql("wide_mixed", "oracle", "t")
