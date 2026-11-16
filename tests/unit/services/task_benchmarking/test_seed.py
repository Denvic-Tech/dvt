import datetime as dt
import io
from dataclasses import replace
from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd
import pyarrow as pa
import pyarrow.csv as pa_csv
import pytest

from services.task_benchmarking import seed, synthetic


class FakeBackend:
    """In-memory SeedBackend: records calls, reports ``existing`` rows before loading."""

    def __init__(self, existing: int | None = None, final_count: int | None = None) -> None:
        self.existing = existing
        self.final_count = final_count
        self.calls: list[str] = []
        self.loaded_rows = 0
        self.loaded = False

    def create_database(self) -> bool:
        self.calls.append("create_database")
        return True

    def connect(self) -> None:
        self.calls.append("connect")

    def count_rows(self) -> int | None:
        self.calls.append("count_rows")
        if not self.loaded:
            return self.existing
        return self.loaded_rows if self.final_count is None else self.final_count

    def execute(self, statement: str) -> None:
        self.calls.append(statement.partition(" (")[0])

    def prepare(self, frame: pd.DataFrame) -> int:
        return len(frame)

    def load(self, payload: int) -> None:
        self.loaded = True
        self.loaded_rows += payload
        self.calls.append("load")

    def flush(self) -> None:
        self.calls.append("flush")

    def close(self) -> None:
        self.calls.append("close")


def _options(**overrides: object) -> seed.SeedOptions:
    options = seed.parse_args(["--db", "postgres", "--rows", "1000", "--npartitions", "4"], {})
    return replace(options, **overrides)


@pytest.mark.parametrize(
    ("db", "port", "database", "user", "batch"),
    [
        ("postgres", 54321, "testdb", "testuser", 100_000),
        ("clickhouse", 8124, "testdb", "testuser", 500_000),
        ("mssql", 11433, "benchdb", "SA", 50_000),
    ],
)
def test_parse_args_uses_per_db_defaults(
    db: str, port: int, database: str, user: str, batch: int
) -> None:
    options = seed.parse_args(["--db", db], {})

    assert (options.host, options.port, options.database, options.user) == (
        "localhost",
        port,
        database,
        user,
    )
    assert options.batch_rows == batch
    assert options.table == "bench_wide_5m"
    assert (options.rows, options.npartitions, options.seed) == (5_000_000, 64, 42)
    assert options.schema == "wide_mixed"
    assert not (options.recreate or options.create_database or options.dry_run)


def test_parse_args_environment_overrides_and_cli_precedence() -> None:
    environ = {
        "DVT_BENCH_MSSQL_HOST": "mssql_test_db",
        "DVT_BENCH_MSSQL_PORT": "1433",
        "DVT_BENCH_MSSQL_PASSWORD": "from-env",
    }

    from_env = seed.parse_args(["--db", "mssql"], environ)
    from_cli = seed.parse_args(["--db", "mssql", "--host", "h", "--port", "1"], environ)

    assert (from_env.host, from_env.port, from_env.password) == ("mssql_test_db", 1433, "from-env")
    assert (from_cli.host, from_cli.port) == ("h", 1)


def test_parse_args_reads_password_from_named_env_and_hides_it_from_repr() -> None:
    options = seed.parse_args(
        ["--db", "postgres", "--password-env", "MY_SECRET"], {"MY_SECRET": "s3cr3t"}
    )

    assert options.password == "s3cr3t"
    assert "s3cr3t" not in repr(options)


@pytest.mark.parametrize(
    "argv",
    [
        ["--db", "postgres", "--password-env", "MISSING"],
        ["--db", "postgres", "--rows", "0"],
        ["--db", "postgres", "--table", "bad;name"],
        ["--db", "postgres", "--password", "a", "--password-env", "B"],
        ["--db", "oracle"],
    ],
)
def test_parse_args_rejects_invalid_input(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        seed.parse_args(argv, {})


def test_run_seed_skips_when_table_already_has_expected_rows(
    capsys: pytest.CaptureFixture[str],
) -> None:
    backend = FakeBackend(existing=1000)

    assert seed.run_seed(_options(), lambda _: backend) == 0

    assert backend.calls == ["connect", "count_rows", "close"]
    assert "already seeded" in capsys.readouterr().out


@pytest.mark.parametrize(("existing", "recreate"), [(None, False), (999, False), (1000, True)])
def test_run_seed_recreates_and_loads_every_partition(
    existing: int | None, recreate: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = FakeBackend(existing=existing)

    assert seed.run_seed(_options(recreate=recreate), lambda _: backend) == 0

    assert backend.calls[:4] == [
        "connect",
        "count_rows",
        'DROP TABLE IF EXISTS "bench_wide_5m"',
        'CREATE TABLE "bench_wide_5m"',
    ]
    assert backend.calls.count("load") == 4
    assert backend.calls[-3:] == ["flush", "count_rows", "close"]
    assert backend.loaded_rows == 1000
    out = capsys.readouterr().out
    assert "seeded 1000 rows into postgres.bench_wide_5m in " in out
    assert "verify: COUNT(*) FROM testdb.bench_wide_5m = 1000 (ok)" in out


def test_run_seed_creates_database_before_connecting() -> None:
    backend = FakeBackend(existing=1000)

    seed.run_seed(_options(create_database=True), lambda _: backend)

    assert backend.calls[:2] == ["create_database", "connect"]


def test_run_seed_fails_when_final_count_mismatches(capsys: pytest.CaptureFixture[str]) -> None:
    backend = FakeBackend(final_count=10)

    assert seed.run_seed(_options(), lambda _: backend) == 1
    assert "(MISMATCH)" in capsys.readouterr().out


def test_dry_run_prints_ddl_without_connecting_or_password(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def factory(_: seed.SeedOptions) -> seed.SeedBackend:
        raise AssertionError("dry run must not create a backend")

    options = _options(dry_run=True, password="top-secret")

    assert seed.run_seed(options, factory) == 0
    out = capsys.readouterr().out
    assert 'CREATE TABLE "bench_wide_5m"' in out
    assert "top-secret" not in out


def test_postgres_prepare_writes_csv_with_unquoted_empty_nulls() -> None:
    options = _options(batch_rows=300)
    frame = synthetic.generate_partition("wide_mixed", synthetic.PartitionSpec(0, 0, 1000), 42)

    chunks = seed.PostgresBackend(options).prepare(frame)

    assert len(chunks) == 4
    parsed = pd.concat(
        pa_csv.read_csv(
            io.BytesIO(chunk),
            read_options=pa_csv.ReadOptions(column_names=synthetic.column_names("wide_mixed")),
            convert_options=pa_csv.ConvertOptions(strings_can_be_null=True),
        ).to_pandas()
        for chunk in chunks
    )
    assert len(parsed) == 1000
    assert parsed["int_b"].isna().sum() == frame["int_b"].isna().sum()
    assert parsed["str_null"].isna().sum() == frame["str_null"].isna().sum()
    first = chunks[0].split(b"\n", 1)[0].decode()
    assert '"group_' in first
    assert first.endswith(frame["date_a"].iloc[0].strftime("%Y-%m-%d"))


def test_mssql_prepare_converts_nulls_dates_and_batches_rows() -> None:
    options = _options(db="mssql", batch_rows=400)
    frame = synthetic.generate_partition("wide_mixed", synthetic.PartitionSpec(0, 0, 1000), 42)

    batches = seed.MssqlBackend(options).prepare(frame)

    assert [len(batch) for batch in batches] == [400, 400, 200]
    rows = [row for batch in batches for row in batch]
    names = synthetic.column_names("wide_mixed")
    int_b = [row[names.index("int_b")] for row in rows]
    assert sum(value is None for value in int_b) == frame["int_b"].isna().sum()
    first = dict(zip(names, rows[0], strict=True))
    assert type(first["date_a"]) is dt.date
    assert isinstance(first["ts_a"], dt.datetime)
    assert type(first["id"]) is int
    assert type(first["bool_a"]) is bool


def test_clickhouse_groups_partitions_into_blocks_of_batch_rows() -> None:
    options = _options(db="clickhouse", batch_rows=500, database="testdb", table="t")
    backend = seed.ClickHouseBackend(options)
    backend._client = MagicMock()
    plan = synthetic.partition_plan(1000, 4)

    for spec in plan:
        backend.load(backend.prepare(synthetic.generate_partition("wide_mixed", spec, 42)))
    backend.flush()

    calls = backend._client.insert_arrow.call_args_list
    assert [call.args[1].num_rows for call in calls] == [500, 500]
    assert all(call.args[0] == "t" and call.kwargs["database"] == "testdb" for call in calls)


def test_clickhouse_arrow_payload_rounds_decimals_client_side() -> None:
    # ClickHouse itself truncates float64 -> Decimal (76577.65 is 76577.6499... as a double).
    backend = seed.ClickHouseBackend(_options(db="clickhouse"))
    frame = synthetic.generate_partition("wide_mixed", synthetic.PartitionSpec(0, 0, 3), 42)
    frame["amount"] = [76577.65, 0.29, 99999.99]

    table = backend.prepare(frame)

    assert table.schema.field("amount").type == pa.decimal128(18, 2)
    assert table.column("amount").to_pylist() == [
        Decimal("76577.65"),
        Decimal("0.29"),
        Decimal("99999.99"),
    ]
