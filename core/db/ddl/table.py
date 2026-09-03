from __future__ import annotations

from typing import List, Optional

import pandas as pd
import sqlalchemy as sa
from sqlalchemy.schema import CreateTable

from core.db.ddl.models import ForeignKeySpec, IndexSpec, TableCreateSpec
from core.db.ddl.parse import extract_create_table_table_and_schema
from core.db.ddl.schema import DIALECTS_WITHOUT_SCHEMA_SUPPORT, ensure_schema_exists
from core.mapper.factory import build_table_from_db_columns, build_table_from_df
from core.types import DBColumn, DataFrameMetadata


def resolve_metadata_schema_for_ddl(
    *,
    dialect_name: str,
    schema_name: Optional[str],
    database_name: Optional[str],
) -> Optional[str]:
    normalized_dialect_name = dialect_name.lower()

    if normalized_dialect_name == "clickhouse":
        return database_name

    if normalized_dialect_name in DIALECTS_WITHOUT_SCHEMA_SUPPORT:
        return None

    return schema_name


def normalize_db_columns_nullable_for_ddl(
    *,
    dialect_name: str,
    columns: List[DBColumn],
    primary_key_cols: Optional[str | List[str]],
    preserve_input_nullable: bool = False,
) -> List[DBColumn]:
    is_clickhouse = dialect_name.lower() == "clickhouse"

    pk_names: set[str] = set()
    if isinstance(primary_key_cols, str) and primary_key_cols:
        pk_names.add(primary_key_cols)
    elif isinstance(primary_key_cols, list):
        pk_names = {name for name in primary_key_cols if isinstance(name, str) and name}

    normalized_columns: List[DBColumn] = []
    for column in columns:
        if column.name in pk_names:
            nullable = False
        elif is_clickhouse or preserve_input_nullable:
            nullable = column.nullable
        else:
            nullable = True
        normalized_columns.append(column.model_copy(update={"nullable": nullable}))

    return normalized_columns


def get_primary_key_cols(
    *,
    index_col: Optional[str | list[str]],
    columns: list[DBColumn],
) -> Optional[str | list[str]]:
    if isinstance(index_col, str):
        return index_col or None

    if isinstance(index_col, list):
        return index_col or None

    inferred_index_cols = [column.name for column in columns if column.index]
    return inferred_index_cols or None


def build_db_columns_from_df_metadata(df_metadata: DataFrameMetadata) -> list[DBColumn]:
    return [
        DBColumn(
            name=column.name,
            dtype=column.dtype,
            nullable=column.nullable,
            index=column.index,
        )
        for column in df_metadata.columns
    ]


def validate_create_table_sql_target(
    create_table_sql: str,
    *,
    engine: sa.Engine,
    expected_table_name: str | None = None,
    expected_schema_name: str | None = None,
) -> tuple[str | None, str | None]:
    parsed_table_name, parsed_schema_name = extract_create_table_table_and_schema(
        create_table_sql,
        engine=engine,
    )
    if expected_table_name and parsed_table_name and parsed_table_name != expected_table_name:
        raise ValueError(
            f"create_table_sql target table '{parsed_table_name}' does not match "
            f"requested table '{expected_table_name}'."
        )
    if expected_schema_name and parsed_schema_name and parsed_schema_name != expected_schema_name:
        raise ValueError(
            f"create_table_sql schema '{parsed_schema_name}' does not match "
            f"requested schema '{expected_schema_name}'."
        )
    return parsed_table_name, parsed_schema_name


def execute_raw_create_table_sql(
    *,
    engine: sa.Engine,
    create_table_sql: str,
    schema_name: str | None = None,
    expected_table_name: str | None = None,
    expected_schema_name: str | None = None,
) -> tuple[str | None, str | None]:
    parsed_table_name, parsed_schema_name = validate_create_table_sql_target(
        create_table_sql,
        engine=engine,
        expected_table_name=expected_table_name,
        expected_schema_name=expected_schema_name,
    )

    effective_schema_name = parsed_schema_name or expected_schema_name or schema_name
    ensure_schema_exists(engine=engine, schema_name=effective_schema_name)
    with engine.begin() as conn:
        conn.execute(sa.text(create_table_sql.rstrip().rstrip(";")))

    return parsed_table_name, effective_schema_name


def create_typed_table_from_dataframe_sample(
    *,
    engine: sa.Engine,
    sample_df: pd.DataFrame,
    table_name: str,
    schema_name: str | None = None,
    spec: TableCreateSpec | None = None,
) -> sa.Table:
    table = _build_typed_table_from_dataframe_sample(
        engine=engine,
        sample_df=sample_df,
        table_name=table_name,
        schema_name=schema_name,
        spec=spec,
    )
    _apply_table_constraints_and_create(engine=engine, table=table, spec=spec or TableCreateSpec())
    return table


def create_typed_table_from_columns(
    *,
    engine: sa.Engine,
    table_name: str,
    columns: list[DBColumn],
    schema_name: str | None = None,
    primary_key_cols: str | list[str] | None = None,
    spec: TableCreateSpec | None = None,
) -> sa.Table:
    table = _build_typed_table_from_columns(
        engine=engine,
        table_name=table_name,
        columns=columns,
        schema_name=schema_name,
        primary_key_cols=primary_key_cols,
        spec=spec,
    )
    _apply_table_constraints_and_create(engine=engine, table=table, spec=spec or TableCreateSpec())
    return table


def build_typed_table_preview_from_columns(
    *,
    engine: sa.Engine,
    table_name: str,
    columns: list[DBColumn],
    schema_name: str | None = None,
    primary_key_cols: str | list[str] | None = None,
    spec: TableCreateSpec | None = None,
) -> sa.Table:
    return _build_typed_table_from_columns(
        engine=engine,
        table_name=table_name,
        columns=columns,
        schema_name=schema_name,
        primary_key_cols=primary_key_cols,
        spec=spec,
        ensure_schema=False,
    )


def generate_create_table_ddl_from_columns(
    *,
    engine: sa.Engine,
    columns: list[DBColumn],
    table_name: str,
    schema_name: str | None = None,
    database_name: str | None = None,
    primary_key_cols: str | list[str] | None = None,
    table_create_spec: TableCreateSpec | None = None,
    preserve_input_nullable: bool = False,
) -> str:
    spec = table_create_spec or TableCreateSpec()
    metadata_schema = resolve_metadata_schema_for_ddl(
        dialect_name=engine.dialect.name,
        schema_name=schema_name,
        database_name=database_name,
    )
    normalized_columns = normalize_db_columns_nullable_for_ddl(
        dialect_name=engine.dialect.name,
        columns=columns,
        primary_key_cols=spec.primary_key_cols or primary_key_cols,
        preserve_input_nullable=preserve_input_nullable,
    )
    table = _build_typed_table_from_columns(
        engine=engine,
        table_name=table_name,
        columns=normalized_columns,
        schema_name=metadata_schema,
        primary_key_cols=primary_key_cols,
        spec=spec,
    )
    return _compile_table_ddl(engine=engine, table=table, spec=spec)


def generate_create_table_ddl_from_metadata(
    *,
    engine: sa.Engine,
    dataframe_metadata: DataFrameMetadata,
    table_name: str,
    schema_name: str | None = None,
    database_name: str | None = None,
    index_col: str | list[str] | None = None,
    table_create_spec: TableCreateSpec | None = None,
) -> str:
    db_columns = build_db_columns_from_df_metadata(dataframe_metadata)
    inferred_primary_key_cols = get_primary_key_cols(index_col=index_col, columns=db_columns)
    return generate_create_table_ddl_from_columns(
        engine=engine,
        columns=db_columns,
        table_name=table_name,
        schema_name=schema_name,
        database_name=database_name,
        primary_key_cols=inferred_primary_key_cols,
        table_create_spec=table_create_spec,
        preserve_input_nullable=False,
    )


def _compile_table_ddl(
    *,
    engine: sa.Engine,
    table: sa.Table,
    spec: TableCreateSpec,
) -> str:
    sql = str(CreateTable(table).compile(dialect=engine.dialect)).strip()
    index_sql_blocks = [
        str(sa.schema.CreateIndex(index).compile(dialect=engine.dialect)).strip()
        for index in _build_indexes_for_table(table=table, spec=spec)
    ]
    sql_blocks = [sql, *index_sql_blocks]
    sql = "\n".join(statement if statement.endswith(";") else f"{statement};" for statement in sql_blocks)
    if not sql.endswith(";"):
        sql += ";"
    return sql


def _build_typed_table_from_dataframe_sample(
    *,
    engine: sa.Engine,
    sample_df: pd.DataFrame,
    table_name: str,
    schema_name: str | None,
    spec: TableCreateSpec | None,
) -> sa.Table:
    spec = spec or TableCreateSpec()
    _validate_typed_spec(engine, spec)
    ensure_schema_exists(engine=engine, schema_name=schema_name)

    metadata = sa.MetaData(schema=schema_name)
    clickhouse_spec = spec.clickhouse
    table = build_table_from_df(
        sample_df,
        table_name=table_name,
        dialect=engine.dialect,
        metadata=metadata,
        primary_key_cols=spec.primary_key_cols,
        partition_by=clickhouse_spec.partition_by if clickhouse_spec else None,
        order_by=clickhouse_spec.order_by if clickhouse_spec else None,
    )
    if clickhouse_spec is not None:
        _apply_clickhouse_engine_spec(table=table, spec=clickhouse_spec)
    return table


def _build_typed_table_from_columns(
    *,
    engine: sa.Engine,
    table_name: str,
    columns: list[DBColumn],
    schema_name: str | None,
    primary_key_cols: str | list[str] | None,
    spec: TableCreateSpec | None,
    ensure_schema: bool = True,
) -> sa.Table:
    spec = spec or TableCreateSpec()
    _validate_typed_spec(engine, spec)
    effective_primary_key_cols = spec.primary_key_cols or primary_key_cols
    if ensure_schema:
        ensure_schema_exists(engine=engine, schema_name=schema_name)

    metadata = sa.MetaData(schema=schema_name)
    clickhouse_spec = spec.clickhouse
    table = build_table_from_db_columns(
        table_name=table_name,
        columns=columns,
        dialect=engine.dialect,
        metadata=metadata,
        primary_key_cols=effective_primary_key_cols,
        partition_by=clickhouse_spec.partition_by if clickhouse_spec else None,
        order_by=clickhouse_spec.order_by if clickhouse_spec else None,
    )
    if clickhouse_spec is not None:
        _apply_clickhouse_engine_spec(table=table, spec=clickhouse_spec)
    return table


def _validate_typed_spec(engine: sa.Engine, spec: TableCreateSpec) -> None:
    is_clickhouse = engine.dialect.name.lower() == "clickhouse"
    if is_clickhouse:
        if spec.foreign_keys:
            raise ValueError("Foreign keys are not supported for ClickHouse typed DDL.")
        if spec.indexes:
            raise ValueError("Indexes are not supported for ClickHouse typed DDL.")
        return

    if spec.clickhouse is not None:
        raise ValueError("ClickHouse table options are not supported by SQL dialect DDL.")


def _apply_table_constraints_and_create(
    *,
    engine: sa.Engine,
    table: sa.Table,
    spec: TableCreateSpec,
) -> None:
    for fk_spec in spec.foreign_keys or []:
        table.append_constraint(_build_foreign_key(fk_spec))

    table.metadata.create_all(engine, tables=[table], checkfirst=False)

    for index in _build_indexes_for_table(table=table, spec=spec):
        index.create(engine)


def _build_foreign_key(spec: ForeignKeySpec) -> sa.ForeignKeyConstraint:
    remote_prefix = f"{spec.ref_schema}.{spec.ref_table}" if spec.ref_schema else spec.ref_table
    remote_columns = [f"{remote_prefix}.{column}" for column in spec.ref_columns]
    return sa.ForeignKeyConstraint(spec.columns, remote_columns, name=spec.name)


def _create_index(*, engine: sa.Engine, table: sa.Table, spec: IndexSpec) -> None:
    _build_indexes_for_table(table=table, spec=TableCreateSpec(indexes=[spec]))[0].create(engine)


def _build_indexes_for_table(*, table: sa.Table, spec: TableCreateSpec) -> list[sa.Index]:
    built_indexes: list[sa.Index] = []
    existing_names = {index.name for index in table.indexes}
    next_suffix = len(existing_names) + 1

    for index_spec in spec.indexes or []:
        missing = [column for column in index_spec.columns if column not in table.c]
        if missing:
            raise ValueError(f"Cannot create index on missing columns {missing!r} for table '{table.fullname}'.")
        index_name = index_spec.name or f"{table.name}_idx_{next_suffix}"
        next_suffix += 1
        if index_name in existing_names:
            raise ValueError(f"Index '{index_name}' already exists for table '{table.fullname}'.")
        built_indexes.append(
            sa.Index(
                index_name,
                *[table.c[column] for column in index_spec.columns],
                unique=index_spec.unique,
            )
        )
        existing_names.add(index_name)

    return built_indexes


def _apply_clickhouse_engine_spec(*, table: sa.Table, spec) -> None:
    try:
        from clickhouse_sqlalchemy import engines
    except Exception as exc:  # pragma: no cover - dependency is required in runtime env
        raise ImportError("For ClickHouse typed DDL install 'clickhouse-sqlalchemy'.") from exc

    engine_cls = getattr(engines, spec.engine_name)
    common_kwargs = {
        "partition_by": _normalize_clickhouse_expr_list(table=table, values=spec.partition_by, as_tuple=True),
        "order_by": _normalize_clickhouse_expr_list(table=table, values=spec.order_by, as_tuple=True),
        "primary_key": _normalize_clickhouse_expr_list(table=table, values=spec.primary_key, as_tuple=True),
        "sample_by": _normalize_clickhouse_expr_list(table=table, values=spec.sample_by, as_tuple=False),
        "ttl": sa.text(spec.ttl_expression) if spec.ttl_expression else None,
        **(spec.settings or {}),
    }
    common_kwargs = {key: value for key, value in common_kwargs.items() if value is not None}

    if spec.engine_name == "ReplacingMergeTree":
        engine = engine_cls(version=spec.version_column, **common_kwargs)
    elif spec.engine_name == "SummingMergeTree":
        engine = engine_cls(columns=spec.summing_columns, **common_kwargs)
    elif spec.engine_name == "CollapsingMergeTree":
        engine = engine_cls(spec.sign_column, **common_kwargs)
    elif spec.engine_name == "VersionedCollapsingMergeTree":
        engine = engine_cls(spec.sign_column, spec.version_column, **common_kwargs)
    elif spec.engine_name == "ReplicatedMergeTree":
        engine = engine_cls(spec.table_path, spec.replica_name, **common_kwargs)
    elif spec.engine_name == "ReplicatedReplacingMergeTree":
        engine = engine_cls(spec.table_path, spec.replica_name, version=spec.version_column, **common_kwargs)
    elif spec.engine_name == "ReplicatedSummingMergeTree":
        engine = engine_cls(spec.table_path, spec.replica_name, columns=spec.summing_columns, **common_kwargs)
    elif spec.engine_name == "ReplicatedAggregatingMergeTree":
        engine = engine_cls(spec.table_path, spec.replica_name, **common_kwargs)
    elif spec.engine_name == "ReplicatedCollapsingMergeTree":
        engine = engine_cls(spec.table_path, spec.replica_name, spec.sign_column, **common_kwargs)
    elif spec.engine_name == "ReplicatedVersionedCollapsingMergeTree":
        engine = engine_cls(
            spec.table_path,
            spec.replica_name,
            spec.sign_column,
            spec.version_column,
            **common_kwargs,
        )
    else:
        engine = engine_cls(**common_kwargs)

    table.engine = engine


def _normalize_clickhouse_expr_list(
    *,
    table: sa.Table,
    values: list[str] | None,
    as_tuple: bool,
):
    if not values:
        return None

    expressions = [_resolve_clickhouse_expression(table=table, value=value) for value in values]
    if len(expressions) == 1 and not as_tuple:
        return expressions[0]
    if len(expressions) == 1 and as_tuple:
        return expressions[0]
    return tuple(expressions)


def _resolve_clickhouse_expression(*, table: sa.Table, value: str):
    rename_map = getattr(table, "rename_map", {})
    resolved_name = rename_map.get(value, value)
    if resolved_name in table.c:
        return sa.column(sa.sql.elements.quoted_name(resolved_name, True))
    return sa.text(value)
