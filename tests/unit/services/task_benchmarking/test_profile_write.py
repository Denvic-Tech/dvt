import re
from datetime import datetime
from pathlib import Path

import pytest

from services.task_benchmarking import profile_write
from services.task_benchmarking.profile_write import (
    Stage,
    attribute_stages,
    builtin_pattern,
    code_pattern,
    diff_stats,
    func_label,
    instrumented_rows,
    parse_args,
)

ROOT = ("app.py", 1, "root")
CHILD = ("app.py", 10, "child")
HELPER = ("lib.py", 5, "helper")
SELECT = ("~", 0, "<built-in method select.select>")


def _exact(key: tuple[str, int, str]) -> str:
    return re.escape(func_label(key))


def test_parse_args_applies_compose_defaults_and_timestamped_out() -> None:
    options = parse_args(["--db", "mysql"], environ={}, now=datetime(2026, 11, 6, 1, 2, 3))

    assert (options.host, options.port, options.database) == ("localhost", 33061, "testdb")
    assert (options.user, options.password) == ("testuser", "testpassword")
    assert (options.rows, options.chunksize, options.repeat, options.warmup) == (62_500, None, 3, 1)
    assert options.table == "bench_profile_wide"
    assert options.out == Path("tmp/task_benchmarking/profiles/2026-11-06T01-02-03_mysql")


def test_parse_args_reads_env_and_flags() -> None:
    environ = {"DVT_BENCH_PG_PORT": "6000", "DVT_BENCH_PG_PASSWORD": "secret", "PW": "from-env"}

    options = parse_args(
        ["--db", "postgres", "--chunksize", "20000", "--repeat", "5", "--out", "x"], environ
    )
    assert (options.port, options.password, options.chunksize, options.repeat) == (
        6000,
        "secret",
        20_000,
        5,
    )
    assert options.out == Path("x")
    assert "secret" not in repr(options)

    assert parse_args(["--db", "postgres", "--password-env", "PW"], environ).password == "from-env"
    with pytest.raises(SystemExit):
        parse_args(["--db", "postgres", "--table", "bad-name"], environ)
    with pytest.raises(SystemExit):
        parse_args(["--db", "oracle"], environ)


def test_attribute_stages_uses_caller_edges_and_exclusive_time() -> None:
    # root (2.0 s) -> child (1.2 s) -> helper (0.3 s) + select (0.5 s); root -> helper (0.2 s).
    stats = {
        ROOT: (1, 1, 0.6, 2.0, {}),
        CHILD: (2, 2, 0.4, 1.2, {ROOT: (2, 2, 0.4, 1.2)}),
        HELPER: (3, 3, 0.5, 0.5, {ROOT: (1, 1, 0.2, 0.2), CHILD: (2, 2, 0.3, 0.3)}),
        SELECT: (5, 5, 0.5, 0.5, {CHILD: (5, 5, 0.5, 0.5)}),
    }
    stages = [
        Stage("root", (_exact(ROOT),)),
        Stage("child", (_exact(CHILD),), parent="root"),
        Stage("helper from child", (_exact(HELPER),), (_exact(CHILD),), "child"),
        Stage("select", (builtin_pattern(SELECT[2]),), parent="child", subtract=False),
        Stage("helper, all callers", (_exact(HELPER),), parent="root", subtract=False),
    ]

    rows = {row["stage"]: row for row in attribute_stages(stats, stages, rows=600)}

    assert rows["root"]["exclusive_s"] == pytest.approx(0.8)  # informational child not subtracted
    assert rows["child"]["cumulative_s"] == pytest.approx(1.2)
    assert rows["child"]["exclusive_s"] == pytest.approx(0.9)
    assert rows["child"]["pct_of_root"] == pytest.approx(60.0)
    assert rows["child"]["rows_per_s"] == pytest.approx(500.0)
    assert (rows["helper from child"]["calls"], rows["helper from child"]["depth"]) == (2, 2)
    assert rows["helper from child"]["cumulative_s"] == pytest.approx(0.3)
    assert rows["[info] select"]["cumulative_s"] == pytest.approx(0.5)
    assert rows["[info] helper, all callers"]["calls"] == 3

    with pytest.raises(ValueError, match="unknown parent"):
        attribute_stages(
            stats, [stages[0], Stage("orphan", (_exact(CHILD),), parent="nope")], rows=1
        )


def test_code_pattern_matches_the_pstats_key_of_a_function() -> None:
    code = test_code_pattern_matches_the_pstats_key_of_a_function.__code__
    label = func_label((code.co_filename, code.co_firstlineno, code.co_name))

    assert re.fullmatch(code_pattern(test_code_pattern_matches_the_pstats_key_of_a_function), label)
    assert re.fullmatch(code_pattern(profile_write.Patcher.wrap), label) is None


def test_diff_stats_keeps_only_calls_between_snapshots() -> None:
    before = {CHILD: (1, 1, 0.1, 0.2, {ROOT: (1, 1, 0.1, 0.2)}), HELPER: (1, 1, 0.1, 0.1, {})}
    after = {
        CHILD: (3, 3, 0.4, 0.8, {ROOT: (3, 3, 0.4, 0.8)}),
        HELPER: (1, 1, 0.1, 0.1, {}),
        SELECT: (2, 2, 0.5, 0.5, {CHILD: (2, 2, 0.5, 0.5)}),
    }

    diff = diff_stats(after, before)

    assert set(diff) == {CHILD, SELECT}
    assert diff[CHILD][:4] == pytest.approx((2, 2, 0.3, 0.6))
    assert diff[CHILD][4][ROOT] == pytest.approx((2, 2, 0.3, 0.6))


def test_instrumented_rows_builds_the_call_path_tree() -> None:
    totals = {
        "partition/a/b": [3, 1.0, 0.1],
        "partition/a": [3, 1.5, 0.5],
        "partition/c": [1, 0.2, 0.2],
        "partition": [1, 2.0, 1.0],
    }

    rows = instrumented_rows(totals, rows=1000)

    assert [(row["stage"], row["depth"]) for row in rows] == [
        ("partition", 0),
        ("a", 1),
        ("b", 2),
        ("c", 1),
    ]
    assert rows[0]["self_wall_s"] == pytest.approx(0.3)
    assert rows[1]["self_wall_s"] == pytest.approx(0.5)
    assert rows[1]["blocked_s"] == pytest.approx(1.0)
    assert rows[1]["pct_of_root"] == pytest.approx(75.0)
