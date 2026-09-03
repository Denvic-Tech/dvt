from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.types import DataType
from src.modules.sql_code_metadata import (
    SQLAlchemyResultMetadataGateway,
    SQLCodeMetadataProvider,
    SQLGlotParserGateway,
    SQLValidationError,
    SQLValidationPolicy,
)
from src.modules.sql_code_metadata.infra import sqlalchemy_result_metadata as result_metadata_module


def _build_validate_use_case():
    provider = SQLCodeMetadataProvider(
        parser_gateway=SQLGlotParserGateway(),
        result_metadata_gateway=SQLAlchemyResultMetadataGateway(),
    )
    return provider.create_validate_sql_use_case()


def _build_extract_use_case():
    provider = SQLCodeMetadataProvider(
        parser_gateway=SQLGlotParserGateway(),
        result_metadata_gateway=SQLAlchemyResultMetadataGateway(),
    )
    return provider.create_extract_sql_code_metadata_use_case()


def _build_engine(dialect_name: str):
    return SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))


def test_sql_validation_policy_normalizes_statement_types() -> None:
    policy = SQLValidationPolicy(
        allowed_statement_types={"select", " Insert "},
        forbidden_statement_types={"create"},
    )

    assert policy.allowed_statement_types == {"SELECT", "INSERT"}
    assert policy.forbidden_statement_types == {"CREATE"}


def test_sql_validation_policy_rejects_overlapping_statement_types() -> None:
    with pytest.raises(ValueError, match="both allowed and forbidden"):
        SQLValidationPolicy(
            allowed_statement_types={"select"},
            forbidden_statement_types={"SELECT"},
        )


@pytest.mark.parametrize(
    ("sql", "dialect_name", "statement_type", "category", "returns_data", "is_query_expression"),
    [
        ("SELECT 1", "postgresql", "SELECT", "read_only", True, True),
        (
            "WITH seeded AS (SELECT 1 AS id) SELECT id FROM seeded",
            "postgresql",
            "SELECT",
            "read_only",
            True,
            True,
        ),
        ("SELECT 1 UNION ALL SELECT 2", None, "SELECT", "read_only", True, True),
        ("INSERT INTO t(id) VALUES (1)", "postgresql", "INSERT", "data_mutating", False, False),
        (
            "INSERT INTO t(id) VALUES (1) RETURNING id",
            "postgresql",
            "INSERT",
            "data_mutating",
            True,
            False,
        ),
        ("UPDATE t SET x = 1 RETURNING id", "postgresql", "UPDATE", "data_mutating", True, False),
        (
            "DELETE FROM t WHERE id = 1 RETURNING id",
            "postgresql",
            "DELETE",
            "data_mutating",
            True,
            False,
        ),
        (
            "INSERT INTO t(id) OUTPUT INSERTED.id VALUES (1)",
            "mssql",
            "INSERT",
            "data_mutating",
            True,
            False,
        ),
        (
            "UPDATE t SET x = 1 OUTPUT INSERTED.id",
            "mssql",
            "UPDATE",
            "data_mutating",
            True,
            False,
        ),
        (
            "DELETE t OUTPUT DELETED.id FROM t WHERE id = 1",
            "mssql",
            "DELETE",
            "data_mutating",
            True,
            False,
        ),
        ("CREATE TABLE t (id INT)", "sqlite", "CREATE", "ddl", False, False),
        (
            (
                "MERGE target AS t USING source AS s ON t.id = s.id "
                "WHEN MATCHED THEN UPDATE SET t.x = s.x"
            ),
            "mssql",
            "MERGE",
            "data_mutating",
            False,
            False,
        ),
    ],
)
def test_validate_sql_reports_statement_shape(
    sql: str,
    dialect_name: str | None,
    statement_type: str,
    category: str,
    returns_data: bool,
    is_query_expression: bool,
) -> None:
    use_case = _build_validate_use_case()
    policy = SQLValidationPolicy(
        allow_multiple_statements=True,
        allow_multiple_result_statements=True,
    )

    report = use_case.execute(sql=sql, dialect_name=dialect_name, policy=policy)

    assert report is not None
    assert report.statement_count == 1
    assert report.statements[0].statement_type == statement_type
    assert report.statements[0].category == category
    assert report.statements[0].returns_data is returns_data
    assert report.statements[0].is_query_expression is is_query_expression


def test_validate_sql_rejects_multiple_statements_when_policy_disallows_them() -> None:
    use_case = _build_validate_use_case()

    with pytest.raises(SQLValidationError, match="Multiple SQL statements are not allowed."):
        use_case.execute(
            sql="SELECT 1; SELECT 2",
            policy=SQLValidationPolicy(allow_multiple_statements=False),
        )


def test_validate_sql_rejects_multiple_result_statements_when_policy_disallows_them() -> None:
    use_case = _build_validate_use_case()
    policy = SQLValidationPolicy(
        allow_multiple_statements=True,
        allow_multiple_result_statements=False,
    )

    with pytest.raises(
        SQLValidationError,
        match="Multiple result-returning statements are not allowed.",
    ):
        use_case.execute(sql="SELECT 1; SELECT 2", policy=policy)


def test_validate_sql_allows_create_then_select_when_only_one_result_statement_exists() -> None:
    use_case = _build_validate_use_case()
    policy = SQLValidationPolicy(
        allow_multiple_statements=True,
        allow_multiple_result_statements=False,
        require_single_result_statement=True,
    )

    report = use_case.execute(
        sql="CREATE TEMP TABLE t (id INT); SELECT * FROM t",
        dialect_name="sqlite",
        policy=policy,
    )

    assert report is not None
    assert report.statement_count == 2
    assert report.result_statement_count == 1


def test_validate_sql_rejects_ddl_when_policy_forbids_it() -> None:
    use_case = _build_validate_use_case()
    policy = SQLValidationPolicy(forbid_ddl_statements=True)

    with pytest.raises(SQLValidationError, match="DDL statements are forbidden."):
        use_case.execute(sql="CREATE TABLE t (id INT)", dialect_name="sqlite", policy=policy)


@pytest.mark.parametrize(
    ("sql", "dialect_name"),
    [
        ("INSERT INTO t(id) VALUES (1)", "postgresql"),
        (
            "MERGE target AS t USING source AS s ON t.id = s.id WHEN MATCHED THEN UPDATE SET t.x = s.x",
            "mssql",
        ),
    ],
)
def test_validate_sql_rejects_data_mutating_statements_when_policy_forbids_them(
    sql: str,
    dialect_name: str,
) -> None:
    use_case = _build_validate_use_case()
    policy = SQLValidationPolicy(forbid_data_mutating_statements=True)

    with pytest.raises(SQLValidationError, match="Data mutating statements are forbidden."):
        use_case.execute(sql=sql, dialect_name=dialect_name, policy=policy)


def test_validate_sql_requires_result_statement() -> None:
    use_case = _build_validate_use_case()
    policy = SQLValidationPolicy(
        allow_multiple_statements=True,
        require_result_statement=True,
    )

    with pytest.raises(SQLValidationError, match="A result-returning statement is required."):
        use_case.execute(sql="INSERT INTO t(id) VALUES (1)", dialect_name="postgresql", policy=policy)


def test_validate_sql_requires_exactly_one_result_statement() -> None:
    use_case = _build_validate_use_case()
    policy = SQLValidationPolicy(
        allow_multiple_statements=True,
        allow_multiple_result_statements=True,
        require_single_result_statement=True,
    )

    with pytest.raises(
        SQLValidationError,
        match="Exactly one result-returning statement is required.",
    ):
        use_case.execute(sql="SELECT 1; SELECT 2", policy=policy)


def test_validate_sql_enforces_allowed_statement_types() -> None:
    use_case = _build_validate_use_case()
    policy = SQLValidationPolicy(allowed_statement_types={"SELECT"})

    with pytest.raises(SQLValidationError, match="SQL statement type 'INSERT' is not allowed."):
        use_case.execute(
            sql="INSERT INTO t(id) VALUES (1)",
            dialect_name="postgresql",
            policy=policy,
        )


def test_validate_sql_enforces_forbidden_statement_types() -> None:
    use_case = _build_validate_use_case()
    policy = SQLValidationPolicy(forbidden_statement_types={"CREATE"})

    with pytest.raises(SQLValidationError, match="SQL statement type 'CREATE' is not allowed."):
        use_case.execute(
            sql="CREATE TABLE t (id INT)",
            dialect_name="sqlite",
            policy=policy,
        )


@pytest.mark.parametrize(
    ("sql", "dialect_name"),
    [
        ("SELECT FROM", "postgresql"),
        ("INSERT INTO t(id) OUTPUT VALUES (1)", "mssql"),
        ("CREATE TABLE t id INT)", "sqlite"),
    ],
)
def test_validate_sql_returns_short_syntax_error_messages(sql: str, dialect_name: str) -> None:
    use_case = _build_validate_use_case()

    with pytest.raises(SQLValidationError, match="SQL contains syntax errors."):
        use_case.execute(sql=sql, dialect_name=dialect_name, policy=SQLValidationPolicy())


def test_validate_sql_skips_parsing_when_parseability_is_disabled_and_no_ast_rules_are_needed() -> None:
    use_case = _build_validate_use_case()
    policy = SQLValidationPolicy(
        validate_parseability=False,
        allow_multiple_statements=True,
        allow_multiple_result_statements=True,
    )

    report = use_case.execute(sql="definitely not valid sql", policy=policy)

    assert report is None


def test_extract_sql_code_metadata_returns_dataframe_metadata_for_select(monkeypatch) -> None:
    use_case = _build_extract_use_case()
    captured: dict[str, str] = {}

    def _fake_describe_query_columns(_engine, raw_query: str):
        captured["raw_query"] = raw_query
        return [("table_code", "nvarchar"), ("row_cap", "int")]

    monkeypatch.setattr(result_metadata_module, "describe_query_columns", _fake_describe_query_columns)

    report = use_case.execute(
        sql="SELECT table_code, row_cap FROM demo_meta.raw_export_tables",
        connection=_build_engine("mssql"),
    )

    assert report.statement_count == 1
    assert report.result_statement_count == 1
    assert report.dataframe_metadata_statement_index == 0
    assert captured["raw_query"] == "SELECT table_code, row_cap FROM demo_meta.raw_export_tables"
    assert report.dataframe_metadata is not None
    assert [column.name for column in report.dataframe_metadata.columns] == ["table_code", "row_cap"]
    assert [column.dtype for column in report.dataframe_metadata.columns] == [DataType.STRING, DataType.INT]


def test_extract_sql_code_metadata_returns_dataframe_metadata_for_mssql_output(monkeypatch) -> None:
    use_case = _build_extract_use_case()

    class _FakeInspector:
        def get_columns(self, table_name: str, schema: str | None = None):
            assert table_name == "raw_export_tables"
            assert schema == "demo_meta"
            return [
                {"name": "id", "type": sa.INTEGER(), "nullable": False},
                {"name": "name", "type": sa.VARCHAR(), "nullable": True},
                {"name": "x", "type": sa.INTEGER(), "nullable": False},
            ]

    import sqlalchemy as sa

    monkeypatch.setattr(result_metadata_module.sa, "inspect", lambda _engine: _FakeInspector())

    report = use_case.execute(
        sql=(
            "UPDATE demo_meta.raw_export_tables "
            "SET x = 1 "
            "OUTPUT INSERTED.id, DELETED.name, INSERTED.x + 1 AS next_x"
        ),
        connection=_build_engine("mssql"),
    )

    assert report.dataframe_metadata_statement_index == 0
    assert report.dataframe_metadata is not None
    assert [column.name for column in report.dataframe_metadata.columns] == ["id", "name", "next_x"]
    assert [column.dtype for column in report.dataframe_metadata.columns] == [
        DataType.INT,
        DataType.STRING,
        DataType.INT,
    ]
    assert [column.nullable for column in report.dataframe_metadata.columns] == [False, True, False]


def test_extract_sql_code_metadata_infers_literal_and_cast_types_for_returning(monkeypatch) -> None:
    use_case = _build_extract_use_case()

    class _FakeInspector:
        def get_columns(self, table_name: str, schema: str | None = None):
            assert table_name == "raw_export_tables"
            assert schema == "public"
            return [
                {"name": "id", "type": sa.INTEGER(), "nullable": False},
            ]

    import sqlalchemy as sa

    monkeypatch.setattr(result_metadata_module.sa, "inspect", lambda _engine: _FakeInspector())

    report = use_case.execute(
        sql=(
            "INSERT INTO public.raw_export_tables(id) VALUES (1) "
            "RETURNING id, 'ok' AS status, CAST(1 AS DECIMAL(10,2)) AS amount"
        ),
        connection=_build_engine("postgresql"),
    )

    assert report.dataframe_metadata is not None
    assert [column.name for column in report.dataframe_metadata.columns] == ["id", "status", "amount"]
    assert [column.dtype for column in report.dataframe_metadata.columns] == [
        DataType.INT,
        DataType.STRING,
        DataType.FLOAT,
    ]
    assert [column.nullable for column in report.dataframe_metadata.columns] == [False, False, None]


def test_extract_sql_code_metadata_uses_first_result_statement(monkeypatch) -> None:
    use_case = _build_extract_use_case()
    captured_queries: list[str] = []

    def _fake_describe_query_columns(_engine, raw_query: str):
        captured_queries.append(raw_query)
        if raw_query == "SELECT 1 AS first_id":
            return [("first_id", "int")]
        if raw_query == "SELECT 2 AS second_id":
            return [("second_id", "int")]
        return []

    monkeypatch.setattr(result_metadata_module, "describe_query_columns", _fake_describe_query_columns)

    report = use_case.execute(
        sql="SELECT 1 AS first_id; SELECT 2 AS second_id",
        connection=_build_engine("postgresql"),
    )

    assert report.result_statement_count == 2
    assert report.dataframe_metadata_statement_index == 0
    assert captured_queries == ["SELECT 1 AS first_id"]
    assert report.dataframe_metadata is not None
    assert [column.name for column in report.dataframe_metadata.columns] == ["first_id"]
