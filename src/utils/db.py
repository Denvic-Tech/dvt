import sqlalchemy as sa
from sqlalchemy.sql.compiler import IdentifierPreparer

from src.logger import logger
from src.utils.security import fernet_decrypt


def ensure_schema_and_create_schema(
        engine: sa.Engine,
        schema_name: str
):
    inspector = sa.inspect(engine)

    try:
        schema_exists = inspector.has_schema(schema_name)
    except NotImplementedError:
        return

    if schema_exists:
        return

    dialect_name = engine.dialect.name.lower()
    if dialect_name in ("sqlite", "mysql", "mariadb", "clickhouse"):
        logger.info(
            f"Dialect Name={dialect_name} does not support schemas; skipping schema creation."
        )
        return

    if dialect_name == "oracle":
        with engine.begin() as conn:
            conn.execute(sa.text(f"CREATE SCHEMA AUTHORIZATION {schema_name}"))
            conn.commit()
        return

    with engine.begin() as conn:
        conn.execute(sa.schema.CreateSchema(schema_name))


def truncate_table(engine, table):
    dialect = engine.dialect.name
    formatted_name = _format_table_identifier(engine, table)

    with engine.begin() as conn:
        if dialect in ("postgresql", "mysql", "mssql", "clickhouse"):
            conn.execute(sa.text(f"TRUNCATE TABLE {formatted_name}"))
        else:
            conn.execute(sa.delete(table))  # TODO: Better recreate from a copy


def decrypt_url(url: sa.URL) -> sa.URL:
    if not url.password:
        return url
    try:
        decrypted_password = fernet_decrypt(url.password)
    except Exception:
        return url

    return url.set(password=decrypted_password)


def _format_table_identifier(engine: sa.Engine, table) -> str:
    preparer: IdentifierPreparer = engine.dialect.identifier_preparer

    if table.schema:
        schema_part = preparer.quote_schema(table.schema)
        table_part = preparer.quote(table.name)
        return f"{schema_part}.{table_part}"

    return preparer.quote(table.name)
