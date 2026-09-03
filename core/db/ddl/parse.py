from __future__ import annotations

from typing import Optional

import sqlalchemy as sa
from sqlglot import exp, parse_one


DIALECT_SA_TO_SG = {
    "postgresql": "postgres",
    "mssql": "tsql",
    "sqlserver": "tsql",
}


def get_sqlglot_dialect(sa_dialect_name: str) -> str:
    return DIALECT_SA_TO_SG.get(sa_dialect_name.lower(), sa_dialect_name.lower())


def get_sqlglot_dialect_from_engine(engine: sa.Engine) -> str:
    return get_sqlglot_dialect(engine.dialect.name)


def parse_create_table(
    create_table_sql: str,
    *,
    engine: Optional[sa.Engine] = None,
    sa_dialect_name: Optional[str] = None,
):
    if not create_table_sql or not create_table_sql.strip():
        raise ValueError("create_table_sql must not be empty")

    if engine is not None:
        dialect_name = get_sqlglot_dialect_from_engine(engine)
    elif sa_dialect_name is not None:
        dialect_name = get_sqlglot_dialect(sa_dialect_name)
    else:
        raise ValueError("Either engine or sa_dialect_name must be provided")

    return parse_one(create_table_sql, read=dialect_name)


def extract_create_table_table_name(
    create_table_sql: str,
    *,
    engine: Optional[sa.Engine] = None,
    sa_dialect_name: Optional[str] = None,
    fallback: Optional[str] = None,
) -> Optional[str]:
    parsed = parse_create_table(
        create_table_sql,
        engine=engine,
        sa_dialect_name=sa_dialect_name,
    )
    table_expr = parsed.find(exp.Table)
    if table_expr is None:
        return fallback

    table_name = table_expr.name
    return table_name or fallback


def extract_create_table_table_and_schema(
    create_table_sql: str,
    *,
    engine: Optional[sa.Engine] = None,
    sa_dialect_name: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    parsed = parse_create_table(
        create_table_sql,
        engine=engine,
        sa_dialect_name=sa_dialect_name,
    )
    table_expr = parsed.find(exp.Table)
    if table_expr is None:
        return None, None

    return table_expr.name, table_expr.db


def extract_create_table_column_names(
    create_table_sql: str,
    *,
    engine: Optional[sa.Engine] = None,
    sa_dialect_name: Optional[str] = None,
) -> list[str]:
    parsed = parse_create_table(
        create_table_sql,
        engine=engine,
        sa_dialect_name=sa_dialect_name,
    )

    names: list[str] = []
    for col_def in parsed.find_all(exp.ColumnDef):
        column_name = col_def.this.name if col_def.this is not None else None
        if column_name:
            names.append(column_name)

    return names
